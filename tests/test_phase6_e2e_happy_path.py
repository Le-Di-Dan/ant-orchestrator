"""CP7 E2E: happy path, durable records, and evidence refs (§matrix S1-S7).

S1: full graph runs to COMPLETED (ScriptedTestPort).
S2: final state has test_status, test_outcome, test_attempt_ref.
S3: test port called exactly once — no duplicate invocations.
S4: retry_count unchanged on single-pass happy path.
S5: evidence refs from TestExecutionOutcome propagated to test_evidence_refs.
S6: durable records — attempt SUCCEEDED, compact JSON stored (DurableTestExecution).
S7: exactly one attempt created on happy path (no duplicates).
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.value_objects import WorkflowRunId
from ant_orchestrator.integration.test_execution_adapter import DurableTestExecution
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.support.cp7_e2e_harness import (
    LOGICAL_ACTION_ID,
    PROFILE_KEY,
    RUN_ID,
    SCOPE,
    THREAD_ID,
    FakeRawAnt,
    ScriptedTestPort,
    e2e_state,
    fake_clock,
    make_db,
    make_orch,
    make_runner,
)


def _success() -> TestExecutionOutcome:
    return TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")


# ---------------------------------------------------------------------------
# S1-S4: graph-routing happy path (ScriptedTestPort, no DB)
# ---------------------------------------------------------------------------


def test_happy_path_completes(tmp_path: Path) -> None:
    """S1: full graph runs to COMPLETED."""
    port = ScriptedTestPort([_success()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "completed"
    assert result.reached_end is True


def test_happy_path_final_state_has_test_fields(tmp_path: Path) -> None:
    """S2: final state carries test_status, test_outcome, test_attempt_ref."""
    port = ScriptedTestPort([_success()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_state.get("test_status") == "pass"
    assert result.final_state.get("test_outcome") == WorkerOutcome.SUCCESS.value
    assert result.final_state.get("test_attempt_ref") == "att-ok"


def test_happy_path_port_called_once(tmp_path: Path) -> None:
    """S3: test port called exactly once — no duplicate invocations."""
    port = ScriptedTestPort([_success()])
    runner = make_runner(tmp_path, test_execution=port)
    runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert port.calls == 1


def test_happy_path_no_retry(tmp_path: Path) -> None:
    """S4: retry_count stays 0 on a single-pass happy path."""
    port = ScriptedTestPort([_success()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_state.get("retry_count", 0) == 0


# ---------------------------------------------------------------------------
# S5: evidence refs propagated from port outcome to final graph state
# ---------------------------------------------------------------------------


def test_evidence_refs_propagated_to_state(tmp_path: Path) -> None:
    """S5: evidence refs from TestExecutionOutcome appear in test_evidence_refs."""
    outcome = TestExecutionOutcome(
        outcome=WorkerOutcome.SUCCESS,
        attempt_ref="att-ev",
        evidence_refs=("worker_run:wr-123", "evidence:ev-456"),
    )
    port = ScriptedTestPort([outcome])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    refs = result.final_state.get("test_evidence_refs", [])
    assert "worker_run:wr-123" in refs
    assert "evidence:ev-456" in refs


# ---------------------------------------------------------------------------
# S6-S7: durable records (DurableTestExecution + real SQLite DB)
# ---------------------------------------------------------------------------


def test_durable_attempt_succeeded_in_db(tmp_path: Path) -> None:
    """S6: DurableTestExecution settles attempt SUCCEEDED with compact JSON in DB."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)
    ant = FakeRawAnt([_success()])
    durable = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)

    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)

    assert result.final_outcome == "completed"
    assert ant.calls == 1
    with SqliteUnitOfWork(db) as uow:
        attempts = uow.execution_attempts.list_for_action(WorkflowRunId(RUN_ID), LOGICAL_ACTION_ID)
    assert len(attempts) == 1
    assert attempts[0].status is ExecutionAttemptStatus.SUCCEEDED
    assert attempts[0].outcome is not None  # compact JSON stored for Window 3 recovery


def test_durable_no_duplicate_attempts(tmp_path: Path) -> None:
    """S7: exactly one attempt is created on a happy path run."""
    c = fake_clock()
    db = make_db(tmp_path, c)
    orch = make_orch(db, c)
    ant = FakeRawAnt([_success()])
    durable = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=SCOPE,
        command_profile_key=PROFILE_KEY,
    )
    runner = make_runner(tmp_path, test_execution=durable, attempt_orchestrator=orch)
    runner.invoke(e2e_state(), thread_id=THREAD_ID)

    with SqliteUnitOfWork(db) as uow:
        attempts = uow.execution_attempts.list_for_action(WorkflowRunId(RUN_ID), LOGICAL_ACTION_ID)
    assert len(attempts) == 1
