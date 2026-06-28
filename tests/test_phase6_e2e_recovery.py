"""CP7 E2E: Window 3 crash-recovery scenarios (§matrix R1-R6).

Window 3: attempt settled (SUCCEEDED or FAILED) but LangGraph checkpoint NOT written.
On re-invoke, DurableTestExecution finds the settled attempt and reconstructs the
compact outcome without calling the backend.

R1: settled SUCCESS → recovered → COMPLETED, NopRawAnt not called.
R2: settled FAILED (compact JSON) → recovered as ESCALATION → SCOPE_CHANGE gate.
R3: settled FAILED (null compact JSON) → ESCALATION fail-closed, no backend.
R4: no new attempt created on Window 3 recovery.
R5: settled RETRYABLE → recovered (compact JSON) → retry → SCOPE_CHANGE gate.
R6: happy path run → compact JSON persisted → subsequent recovery would succeed.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.core.domain.value_objects import WorkflowRunId
from ant_orchestrator.integration.test_execution_adapter import (
    DurableTestExecution,
    _to_compact_json,
)
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.support.cp7_e2e_harness import (
    LOGICAL_ACTION_ID,
    PROFILE_KEY,
    RUN_ID,
    SCOPE,
    THREAD_ID,
    FakeRawAnt,
    NopRawAnt,
    e2e_state,
    fake_clock,
    make_db,
    make_orch,
    make_runner,
)


def _failed_outcome() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="settled-1",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
        category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
    )


def _retryable_outcome() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.RETRYABLE_FAILURE,
        attempt_ref="settled-1",
        disposition=RecoveryDisposition.RETRY,
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        category=FailureCategory.TRANSIENT_INTERRUPTION,
    )


def _success_outcome() -> TestExecutionOutcome:
    return TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")


# ---------------------------------------------------------------------------
# R1: settled SUCCESS → recovered → COMPLETED, backend not called
# ---------------------------------------------------------------------------


def test_w3_settled_success_recovered_no_backend_call(tmp_path: Path) -> None:
    """R1: pre-seeded SUCCEEDED attempt → graph recovers, NopRawAnt not called."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)

    attempt_id = orch.before_execute(RUN_ID, LOGICAL_ACTION_ID)
    orch.after_execute(attempt_id, WorkerOutcome.SUCCESS, compact_json=None)

    nop = NopRawAnt()
    durable = DurableTestExecution(
        ant=nop,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)

    assert nop.calls == 0, "backend must not be called in Window 3 recovery"
    assert result.final_outcome == "completed"


# ---------------------------------------------------------------------------
# R2: settled FAILED (compact JSON) → ESCALATION → SCOPE_CHANGE gate
# ---------------------------------------------------------------------------


def test_w3_settled_failed_compact_json_escalates(tmp_path: Path) -> None:
    """R2: pre-seeded FAILED with compact JSON → recovered ESCALATION → gate."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)

    failed = _failed_outcome()
    attempt_id = orch.before_execute(RUN_ID, LOGICAL_ACTION_ID)
    orch.after_execute(attempt_id, WorkerOutcome.ESCALATION, compact_json=_to_compact_json(failed))

    nop = NopRawAnt()
    durable = DurableTestExecution(
        ant=nop,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)

    assert nop.calls == 0
    # ESCALATION → test_status="escalate" → SCOPE_CHANGE gate → interrupt
    assert result.reached_end is False
    assert result.interrupt is not None


# ---------------------------------------------------------------------------
# R3: settled FAILED (null compact JSON) → ESCALATION fail-closed
# ---------------------------------------------------------------------------


def test_w3_null_compact_json_fail_closed(tmp_path: Path) -> None:
    """R3: FAILED + null compact_json → _indeterminate_outcome (ESCALATION), no backend."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)

    attempt_id = orch.before_execute(RUN_ID, LOGICAL_ACTION_ID)
    orch.after_execute(attempt_id, WorkerOutcome.PERMANENT_FAILURE, compact_json=None)

    nop = NopRawAnt()
    durable = DurableTestExecution(
        ant=nop,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)

    assert nop.calls == 0
    # Indeterminate → ESCALATION → SCOPE_CHANGE gate
    assert result.reached_end is False
    assert result.interrupt is not None


# ---------------------------------------------------------------------------
# R4: no new attempt created on Window 3 recovery
# ---------------------------------------------------------------------------


def test_w3_no_new_attempt_on_recovery(tmp_path: Path) -> None:
    """R4: Window 3 recovery leaves exactly 1 attempt in DB (original, no new one)."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)

    attempt_id = orch.before_execute(RUN_ID, LOGICAL_ACTION_ID)
    orch.after_execute(attempt_id, WorkerOutcome.SUCCESS, compact_json=None)

    durable = DurableTestExecution(
        ant=NopRawAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)
    runner.invoke(e2e_state(), thread_id=THREAD_ID)

    with SqliteUnitOfWork(db) as uow:
        attempts = uow.execution_attempts.list_for_action(WorkflowRunId(RUN_ID), LOGICAL_ACTION_ID)
    assert len(attempts) == 1


# ---------------------------------------------------------------------------
# R5: settled RETRYABLE (compact JSON) → retry outcome recovered → gate
# ---------------------------------------------------------------------------


def test_w3_settled_retryable_compact_json_recovered(tmp_path: Path) -> None:
    """R5: settled RETRYABLE (compact JSON) → recovered RETRYABLE → retry or gate."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)

    retry = _retryable_outcome()
    attempt_id = orch.before_execute(RUN_ID, LOGICAL_ACTION_ID)
    orch.after_execute(
        attempt_id, WorkerOutcome.RETRYABLE_FAILURE, compact_json=_to_compact_json(retry)
    )

    nop = NopRawAnt()
    durable = DurableTestExecution(
        ant=nop,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    runner.invoke(e2e_state(), thread_id=THREAD_ID)

    # RETRYABLE → retries until budget exhausted → RETRY_LIMIT gate
    # (NopRawAnt raises on second+ call, so budget must exhaust without backend calls)
    assert nop.calls == 0, "backend must not be called on first recovery"


# ---------------------------------------------------------------------------
# R6: happy path run → compact JSON persisted (proves recovery chain intact)
# ---------------------------------------------------------------------------


def test_happy_path_compact_json_stored_for_recovery(tmp_path: Path) -> None:
    """R6: normal run settles attempt with compact JSON → Window 3 recovery ready."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)
    ant = FakeRawAnt([_success_outcome()])
    durable = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)

    assert result.final_outcome == "completed"
    with SqliteUnitOfWork(db) as uow:
        attempts = uow.execution_attempts.list_for_action(WorkflowRunId(RUN_ID), LOGICAL_ACTION_ID)
    assert attempts[0].status is ExecutionAttemptStatus.SUCCEEDED
    assert attempts[0].outcome is not None  # compact JSON stored; recovery chain ready
