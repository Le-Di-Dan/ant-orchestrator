"""CP6 cancellation-matrix tests (§4, timings 4.1–4.6).

Tests that cancellation at each graph boundary produces the correct result:
  4.1 before test node         — backend NOT called, final_outcome CANCELLED.
  4.2 before backend run       — same probe timing as 4.1 with transient port.
  4.3 during container run     — cancel detected at next boundary, backend ran once.
  4.4 after backend, pre-commit — cancel at persist_handoff → CANCELLED.
  4.5 between retries          — no new retry after cancel.
  4.6 during approval interrupt — cancel → CANCELLED without retry/regroup.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)
from ant_orchestrator.core.domain.enums import WorkflowRunStatus
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workflows.state import new_graph_state
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    InterruptRunner,
    add_task,
    build_services,
    uow_factory,
)

# ---------------------------------------------------------------------------
# Helpers / fakes
# ---------------------------------------------------------------------------


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


def _success_outcome() -> TestExecutionOutcome:
    return TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")


def _transient_outcome() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.RETRYABLE_FAILURE,
        attempt_ref="att-t",
        disposition=RecoveryDisposition.RETRY,
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        category=FailureCategory.TRANSIENT_INTERRUPTION,
    )


class _FakeWorker:
    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        return WorkerExecutionResult(outcome=WorkerOutcome.SUCCESS, detail="ok")


class _CountingTestPort:
    __test__ = False

    def __init__(self, outcomes: list[TestExecutionOutcome]) -> None:
        self._outcomes = outcomes
        self.calls = 0

    def execute(
        self,
        *,
        task_id: str,
        run_id: str,
        context_manifest_digest: str = "",
    ) -> TestExecutionOutcome:
        self.calls += 1
        return self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]


class _AlwaysCancelProbe:
    """Probe that always reports cancel_requested (fires immediately at node entry)."""

    def is_cancel_requested(self, run_id: str) -> bool:
        return True


class _CancelAfterNProbe:
    """Probe that fires True only after N calls (lets first N nodes proceed)."""

    def __init__(self, fire_after: int = 1) -> None:
        self._fire_after = fire_after
        self._calls = 0

    def is_cancel_requested(self, run_id: str) -> bool:
        self._calls += 1
        return self._calls > self._fire_after


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    return db


def _runner_with(
    tmp_path: Path,
    *,
    port: object | None = None,
    probe: object | None = None,
) -> WorkflowRunner:
    return WorkflowRunner(
        worker=_FakeWorker(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        cancellation_probe=probe,  # type: ignore[arg-type]
        test_execution=port,  # type: ignore[arg-type]
    )


def _state(run_id: str = "R1") -> dict[str, object]:
    return new_graph_state(task_id="T1", workflow_run_id=run_id, base_retry_limit=2)


# ---------------------------------------------------------------------------
# 4.1 — cancel before test node (probe fires at test node entry)
# ---------------------------------------------------------------------------


def test_cancel_before_test_node_no_backend_call(tmp_path: Path) -> None:
    """4.1: cancel probe fires before test node → backend NOT called, CANCELLED."""
    port = _CountingTestPort([_success_outcome()])
    runner = _runner_with(tmp_path, port=port, probe=_AlwaysCancelProbe())

    result = runner.invoke(_state("R1"), thread_id="wf:R1")

    assert result.final_outcome == "cancelled"
    assert port.calls == 0, "test port must not be called when cancel fires at node entry"


# ---------------------------------------------------------------------------
# 4.2 — cancel after DocAnt, before backend run
# ---------------------------------------------------------------------------


def test_cancel_before_backend_transient_not_retried(tmp_path: Path) -> None:
    """4.2: cancel fires before backend → CANCELLED, transient port never called."""
    port = _CountingTestPort([_transient_outcome()])
    runner = _runner_with(tmp_path, port=port, probe=_AlwaysCancelProbe())

    result = runner.invoke(_state("R2"), thread_id="wf:R2")

    assert result.final_outcome == "cancelled"
    assert port.calls == 0


# ---------------------------------------------------------------------------
# 4.3 — cancel during container run (architectural boundary)
# ---------------------------------------------------------------------------


def test_cancel_during_run_detected_at_next_boundary(tmp_path: Path) -> None:
    """4.3: cancel set after backend completes is detected at persist_handoff boundary.

    The probe fires at node-entry boundaries: execute_stub (call 1) and test (call 2).
    fire_after=2 lets execute_stub and test proceed; cancel fires at persist_handoff (call 3).
    """
    port = _CountingTestPort([_success_outcome()])
    probe = _CancelAfterNProbe(fire_after=2)
    runner = _runner_with(tmp_path, port=port, probe=probe)

    result = runner.invoke(_state("R3"), thread_id="wf:R3")

    assert port.calls >= 1, "backend should have been called before cancel was detected"
    assert result.final_outcome == "cancelled"


# ---------------------------------------------------------------------------
# 4.4 — cancel after backend success, before state commit
# ---------------------------------------------------------------------------


def test_cancel_after_backend_success_final_outcome_cancelled(tmp_path: Path) -> None:
    """4.4: cancel request after backend success → final status CANCELLED, port called once.

    fire_after=2: execute_stub → False, test → False (backend runs), persist_handoff → True.
    """
    port = _CountingTestPort([_success_outcome()])
    probe = _CancelAfterNProbe(fire_after=2)
    runner = _runner_with(tmp_path, port=port, probe=probe)

    result = runner.invoke(_state("R4"), thread_id="wf:R4")

    assert result.final_outcome == "cancelled"
    assert port.calls == 1, "backend called exactly once; no retry on cancel"


# ---------------------------------------------------------------------------
# 4.5 — cancel between retries (probe fires at test node re-entry)
# ---------------------------------------------------------------------------


def test_cancel_between_retries_no_new_retry_attempt(tmp_path: Path) -> None:
    """4.5: transient failure + cancel at retry test-node → CANCELLED, one backend call.

    Retry path: execute_stub (call 1) → test-node-1 (call 2, backend runs, TRANSIENT)
    → validate routes directly to PHASE_TEST → test-node-2 (call 3, cancel detected).
    fire_after=2: calls 1 and 2 → False; call 3 → True (cancel before retry backend).
    """
    port = _CountingTestPort([_transient_outcome()])
    probe = _CancelAfterNProbe(fire_after=2)
    runner = _runner_with(tmp_path, port=port, probe=probe)

    result = runner.invoke(_state("R5"), thread_id="wf:R5")

    assert result.final_outcome == "cancelled"
    assert port.calls == 1, "exactly one backend call; retry was cancelled"


# ---------------------------------------------------------------------------
# 4.6 — cancel during approval interrupt
# ---------------------------------------------------------------------------


def test_cancel_during_approval_routes_cancelled(tmp_path: Path) -> None:
    """4.6: workflow paused at approval → cancel → CANCELLED, no retry/regroup."""
    clock = _clock()
    ids = SequentialIdGenerator()
    db = _make_db(tmp_path, clock)

    runner = InterruptRunner(
        worker=_FakeWorker(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
    )
    run_svc, _resolve, _recon, _pause, _complete_svc = build_services(db, runner, clock, ids)

    # Start workflow → hits approval interrupt.
    outcome = run_svc.execute("T1")
    assert outcome.status == "waiting_for_approval"
    run_id = outcome.run_id

    # Issue cancel via CancelTask service.
    from ant_orchestrator.application.services.cancel_task import CancelTask

    uow_f = uow_factory(db)
    cancel_svc = CancelTask(runner, uow_f, _complete_svc, clock=clock, ids=ids)
    cancel_svc.cancel("T1")

    # Final run status = CANCELLED.
    with SqliteUnitOfWork(db) as uow:
        run = uow.workflow_runs.get(WorkflowRunId(run_id))
    assert run.status is WorkflowRunStatus.CANCELLED


# ---------------------------------------------------------------------------
# No retry after cancel — regression guard
# ---------------------------------------------------------------------------


def test_cancelled_state_never_creates_new_attempt(tmp_path: Path) -> None:
    """Terminal CANCELLED state must not create a new worker attempt."""
    port = _CountingTestPort([_success_outcome()])
    runner = _runner_with(tmp_path, port=port, probe=_AlwaysCancelProbe())

    result = runner.invoke(_state("R6"), thread_id="wf:R6")

    assert result.final_outcome == "cancelled"
    # Port never called → no worker attempt was created.
    assert port.calls == 0
    assert result.reached_end is True
