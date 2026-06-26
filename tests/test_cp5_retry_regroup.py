"""CP5 — Retry/Regroup/Escalation + ExecutionAttempt tests.

Covers:
  Scenario D: off-by-one retry (base=2 → 3 attempts before RETRY_LIMIT gate)
  Scenario E: regroup → SCOPE_CHANGE escalation (max_regroups=1)
  Scenario F: escalation payload carries diagnostic counters
  RetryGrant: approve RETRY_LIMIT → retry_extension_count+1, then execute succeeds
  RetryGrant bound: second RETRY_LIMIT approval → fail-closed (FAILED)
  ExecutionAttempt lifecycle: created per attempt, settled after worker
  INDETERMINATE recovery: stale STARTED → INDETERMINATE + new attempt
"""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from pathlib import Path

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import (
    ExecutionAttemptStatus,
    GateType,
    TaskStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    ExecutionAttemptId,
    TaskId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ExecutionAttempt
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, build_services, create_running_run, uow_factory
from tests.support.workflow_runtime import CountingWorker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _runner_with_attempts(
    tmp_path: Path,
    worker: CountingWorker,
    database: Database,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> WorkflowRunner:
    uow_f = uow_factory(database)
    orchestrator = AttemptOrchestrator(uow_f, clock=clock, ids=id_gen)
    return WorkflowRunner(
        worker=worker,
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        attempt_orchestrator=orchestrator,
    )


def _attempt_rows(database: Database) -> list[sqlite3.Row]:
    with sqlite3.connect(str(database.path)) as conn:
        conn.row_factory = sqlite3.Row
        return conn.execute("SELECT * FROM execution_attempts ORDER BY attempt_no").fetchall()


# ---------------------------------------------------------------------------
# Scenario D — off-by-one retry (PHASE_4_PLAN C.9b / MICRO #1)
# ---------------------------------------------------------------------------


def test_scenario_d_retry_off_by_one_escalates_after_3_attempts(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """D: base_retry_limit=2 → initial + 2 retries = 3 attempts before RETRY_LIMIT gate."""
    worker = CountingWorker(WorkerOutcome.RETRYABLE_FAILURE)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    outcome = run_svc.execute("T1")

    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert worker.calls == 3  # initial (attempt 1) + 2 retries (attempts 2 & 3)

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(run.id)
    assert approval is not None
    assert approval.gate_type is GateType.RETRY_LIMIT

    rows = _attempt_rows(database)
    assert len(rows) == 3
    assert all(r["status"] == ExecutionAttemptStatus.FAILED.value for r in rows)
    assert [r["attempt_no"] for r in rows] == [1, 2, 3]


def test_scenario_d_retry_count_in_approval_payload(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Scenario F (retry): RETRY_LIMIT gate payload contains retry_count + effective limit."""
    worker = CountingWorker(WorkerOutcome.RETRYABLE_FAILURE)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(run.id)
    # Counters are in the sanitized_payload nested inside the request_payload (approval_intent).
    sanitized = (approval.request_payload or {}).get("sanitized_payload") or {}
    assert sanitized.get("retry_count") == 2
    assert sanitized.get("effective_retry_limit") == 2  # base=2, extension=0


# ---------------------------------------------------------------------------
# Scenario E — regroup then SCOPE_CHANGE escalation
# ---------------------------------------------------------------------------


def test_scenario_e_regroup_then_scope_change_escalation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """E: REVIEW_REGROUP worker → regroup once → second regroup exceeds max → SCOPE_CHANGE."""
    worker = CountingWorker(WorkerOutcome.REVIEW_REGROUP)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    outcome = run_svc.execute("T1")

    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert worker.calls == 2  # attempt 1 → regroup → attempt 2 → SCOPE_CHANGE

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(run.id)
    assert approval.gate_type is GateType.SCOPE_CHANGE
    sanitized = (approval.request_payload or {}).get("sanitized_payload") or {}
    assert sanitized.get("regroup_count") == 1  # Scenario F payload check


# ---------------------------------------------------------------------------
# RetryGrant — approve RETRY_LIMIT → retry_extension_count += 1
# ---------------------------------------------------------------------------


class _FailThenSucceedWorker:
    """Fails exactly ``fail_count`` times then returns SUCCESS."""

    def __init__(self, fail_count: int) -> None:
        self.calls = 0
        self._fail_count = fail_count

    def execute(self, intent: object) -> object:
        from ant_orchestrator.application.ports.worker import WorkerExecutionResult

        self.calls += 1
        outcome = (
            WorkerOutcome.RETRYABLE_FAILURE
            if self.calls <= self._fail_count
            else WorkerOutcome.SUCCESS
        )
        return WorkerExecutionResult(outcome=outcome, detail="x")


def test_retry_grant_approve_allows_one_extra_retry_then_completes(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Approve RETRY_LIMIT gate increments extension_count; graph then completes on attempt 4."""
    worker = _FailThenSucceedWorker(fail_count=3)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    pause_outcome = run_svc.execute("T1")
    assert pause_outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert worker.calls == 3

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(run.id)
    assert approval.gate_type is GateType.RETRY_LIMIT

    # Approve the RETRY_LIMIT gate → RetryGrant → attempt 4 succeeds
    complete_outcome = resolve_svc.approve("T1")
    assert complete_outcome.status == TaskStatus.COMPLETED.value
    assert worker.calls == 4  # grant allowed one more, 4th succeeds

    rows = _attempt_rows(database)
    assert len(rows) == 4
    assert rows[-1]["status"] == ExecutionAttemptStatus.SUCCEEDED.value


def test_retry_grant_bound_fail_closed_on_second_approval(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Second RETRY_LIMIT approval when extension_count already at max → FAILED (fail-closed)."""
    worker = CountingWorker(WorkerOutcome.RETRYABLE_FAILURE)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    # First run: 3 attempts → RETRY_LIMIT gate
    run_svc.execute("T1")
    assert worker.calls == 3

    # First approve: RetryGrant (extension 0→1); graph runs 2 more → 2nd RETRY_LIMIT gate
    second_pause = resolve_svc.approve("T1")
    assert second_pause.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert worker.calls == 5  # 3 + 2 more (retry_count 2→3, 3>=3 → escalate again)

    # Second approve: extension_count=1 already at MAX_RETRY_EXTENSIONS=1 → fail-closed
    failed_outcome = resolve_svc.approve("T1")
    assert failed_outcome.status == TaskStatus.FAILED.value
    assert worker.calls == 5  # no extra worker call (FAILED without execute)


# ---------------------------------------------------------------------------
# ExecutionAttempt lifecycle — direct AttemptOrchestrator test
# ---------------------------------------------------------------------------


def test_execution_attempt_created_and_settled_per_worker_call(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """ExecutionAttempt is created before execute and SUCCEEDED after SUCCESS outcome."""
    worker = CountingWorker(WorkerOutcome.SUCCESS)
    runner = _runner_with_attempts(tmp_path, worker, database, clock, id_gen)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")

    rows = _attempt_rows(database)
    assert len(rows) == 1
    assert rows[0]["status"] == ExecutionAttemptStatus.SUCCEEDED.value
    assert rows[0]["attempt_no"] == 1


# ---------------------------------------------------------------------------
# INDETERMINATE recovery (PHASE_4_PLAN MICRO #3)
# ---------------------------------------------------------------------------


def test_indeterminate_recovery_stale_started_becomes_indeterminate(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Stale STARTED attempt (lease expired) → INDETERMINATE + new STARTED attempt created."""
    add_task(database, "T-stale", clock=clock)
    run_id = WorkflowRunId("R-stale")
    create_running_run(database, run_id, "T-stale", clock, id_gen)

    logical_action_id = "action-1"
    expired_lease = UtcTimestamp(clock.now().value - timedelta(seconds=1))
    stale = ExecutionAttempt(
        id=ExecutionAttemptId("STALE-1"),
        workflow_run_id=run_id,
        logical_action_id=logical_action_id,
        attempt_no=1,
        status=ExecutionAttemptStatus.STARTED,
        created_at=clock.now(),
        owner_token="old-owner",
        lease_expires_at=expired_lease,
        started_at=clock.now(),
    )
    with SqliteUnitOfWork(database) as uow:
        uow.execution_attempts.add(stale)

    orchestrator = AttemptOrchestrator(uow_factory(database), clock=clock, ids=id_gen)
    new_id = orchestrator.before_execute(run_id.value, logical_action_id)

    assert new_id != "STALE-1"
    rows = _attempt_rows(database)
    assert len(rows) == 2
    assert rows[0]["id"] == "STALE-1"
    assert rows[0]["status"] == ExecutionAttemptStatus.INDETERMINATE.value
    assert rows[1]["status"] == ExecutionAttemptStatus.STARTED.value
    assert rows[1]["attempt_no"] == 2


def test_non_stale_started_attempt_reused_idempotently(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """A non-stale STARTED attempt is re-used (idempotent resume path, no duplicate)."""
    add_task(database, "T-valid", clock=clock)
    run_id = WorkflowRunId("R-valid")
    create_running_run(database, run_id, "T-valid", clock, id_gen)

    logical_action_id = "action-2"
    valid_lease = UtcTimestamp(clock.now().value + timedelta(hours=1))
    existing = ExecutionAttempt(
        id=ExecutionAttemptId("EA-valid"),
        workflow_run_id=run_id,
        logical_action_id=logical_action_id,
        attempt_no=1,
        status=ExecutionAttemptStatus.STARTED,
        created_at=clock.now(),
        owner_token="current-owner",
        lease_expires_at=valid_lease,
        started_at=clock.now(),
    )
    with SqliteUnitOfWork(database) as uow:
        uow.execution_attempts.add(existing)

    orchestrator = AttemptOrchestrator(uow_factory(database), clock=clock, ids=id_gen)
    returned_id = orchestrator.before_execute(run_id.value, logical_action_id)

    assert returned_id == "EA-valid"
    rows = _attempt_rows(database)
    assert len(rows) == 1  # no duplicate created
