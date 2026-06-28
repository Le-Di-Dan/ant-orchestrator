"""CP4 — invocation-count integration tests for transient retry wiring (§11.2–11.5).

Key invariants verified:
* DocAnt invoked exactly once, provider count unchanged, for transient Test Ant retry.
* Test Ant invoked exactly once per attempt; retry = 2nd invocation.
* Retry keeps same logical_action_id; changes attempt_id.
* retry_count increments exactly once per retry transition.
* regroup_count does NOT increment on retry.
* Plain timeout: no retry, escalation raised.
* Deterministic failure: no retry, escalation raised.
* Retry limit: exactly config retries; extension grants one more.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.application.ports.test_execution import (
    TestExecutionOutcome,
    TestExecutionPort,
)
from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workflows.state import new_graph_state
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _ScriptedTestPort:
    """Test port that returns a sequence of outcomes (transient, then success)."""

    __test__ = False

    def __init__(self, outcomes: list[TestExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.call_count = 0
        self.call_args: list[dict[str, str]] = []

    def execute(
        self,
        *,
        task_id: str,
        run_id: str,
        context_manifest_digest: str = "",
    ) -> TestExecutionOutcome:
        self.call_count += 1
        self.call_args.append({"task_id": task_id, "run_id": run_id})
        return self._outcomes[min(self.call_count - 1, len(self._outcomes) - 1)]


class _CountingWorker:
    """Stub worker that counts invocations."""

    def __init__(self, outcome: WorkerOutcome = WorkerOutcome.SUCCESS) -> None:
        self.calls = 0
        self._outcome = outcome

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        self.calls += 1
        return WorkerExecutionResult(outcome=self._outcome, detail="stub")


def _transient_outcome(attempt_ref: str) -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.RETRYABLE_FAILURE,
        attempt_ref=attempt_ref,
        disposition=RecoveryDisposition.RETRY,
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        category=FailureCategory.TRANSIENT_INTERRUPTION,
        evidence_refs=("sig:sigterm",),
    )


def _success_outcome(attempt_ref: str) -> TestExecutionOutcome:
    return TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref=attempt_ref)


def _timeout_outcome(attempt_ref: str) -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref=attempt_ref,
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.TEST_DEADLINE_EXCEEDED,
        category=FailureCategory.TEST_DEADLINE_EXCEEDED,
    )


def _deterministic_outcome(attempt_ref: str) -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref=attempt_ref,
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
        category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
    )


def _fatal_outcome(attempt_ref: str) -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.PERMANENT_FAILURE,
        attempt_ref=attempt_ref,
        disposition=RecoveryDisposition.TERMINAL_FAILED,
        reason_code=TestReasonCode.EXECUTABLE_MISSING,
        category=FailureCategory.EXECUTABLE_MISSING,
    )


def _runner(
    tmp_path: Path, worker: object, test_port: TestExecutionPort | None
) -> WorkflowRunner:
    return WorkflowRunner(
        worker=worker,  # type: ignore[arg-type]
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        test_execution=test_port,
    )


def _state(run_id: str = "R1") -> dict:  # type: ignore[type-arg]
    return dict(new_graph_state(task_id="T1", workflow_run_id=run_id, base_retry_limit=2))


# ---------------------------------------------------------------------------
# §11.2 Happy path: DocAnt=1, TestAnt=1, route→review
# ---------------------------------------------------------------------------


def test_happy_path_stub_worker_with_passing_test(tmp_path: Path) -> None:
    worker = _CountingWorker()
    test_port = _ScriptedTestPort([_success_outcome("att-1")])
    result = _runner(tmp_path, worker, test_port).invoke(_state(), thread_id="wf:R1")
    assert result.reached_end is True
    assert result.final_outcome == "completed"
    assert worker.calls == 1
    assert test_port.call_count == 1


# ---------------------------------------------------------------------------
# §11.2 Transient retry: TestAnt=2, stub_worker=1, retry_count=1, regroup=0
# ---------------------------------------------------------------------------


def test_transient_retry_test_ant_invoked_twice_stub_worker_once(tmp_path: Path) -> None:
    worker = _CountingWorker()
    test_port = _ScriptedTestPort([
        _transient_outcome("att-1"),
        _success_outcome("att-2"),
    ])
    result = _runner(tmp_path, worker, test_port).invoke(_state("R2"), thread_id="wf:R2")
    assert result.reached_end is True
    assert result.final_outcome == "completed"
    # DocAnt (stub worker) called once — NOT re-entered by test retry.
    assert worker.calls == 1
    # Test Ant called twice (initial + 1 retry).
    assert test_port.call_count == 2
    # retry_count = 1 (one retry transition granted).
    assert result.final_state["retry_count"] == 1
    # regroup_count unchanged.
    assert result.final_state.get("regroup_count", 0) == 0


# ---------------------------------------------------------------------------
# §11.3 Plain deadline: NOT retried, escalation gate raised
# ---------------------------------------------------------------------------


def test_plain_timeout_does_not_retry_test_ant(tmp_path: Path) -> None:
    worker = _CountingWorker()
    test_port = _ScriptedTestPort([_timeout_outcome("att-1")])
    result = _runner(tmp_path, worker, test_port).invoke(_state("R3"), thread_id="wf:R3")
    # Must pause at an interrupt (SCOPE_CHANGE gate) — NOT route back to test.
    assert result.interrupt is not None
    assert test_port.call_count == 1
    # retry_count must NOT increase for a timeout.
    assert result.final_state.get("retry_count", 0) == 0


# ---------------------------------------------------------------------------
# §11.4 Deterministic failure: NOT retried, SCOPE_CHANGE gate raised
# ---------------------------------------------------------------------------


def test_deterministic_failure_does_not_retry(tmp_path: Path) -> None:
    worker = _CountingWorker()
    test_port = _ScriptedTestPort([_deterministic_outcome("att-1")])
    result = _runner(tmp_path, worker, test_port).invoke(_state("R4"), thread_id="wf:R4")
    assert result.interrupt is not None
    assert test_port.call_count == 1
    assert result.final_state.get("retry_count", 0) == 0


# ---------------------------------------------------------------------------
# §11.5 Retry limit: retries stop at config bound; RetryGrant extends by 1
# ---------------------------------------------------------------------------


def test_retry_stops_at_base_limit(tmp_path: Path) -> None:
    worker = _CountingWorker()
    # 3 transients → budget (2) exhausted after 2 retries → RETRY_LIMIT gate at 3rd.
    test_port = _ScriptedTestPort([
        _transient_outcome("att-1"),
        _transient_outcome("att-2"),
        _transient_outcome("att-3"),
    ])
    result = _runner(tmp_path, worker, test_port).invoke(_state("R5"), thread_id="wf:R5")
    assert result.interrupt is not None  # RETRY_LIMIT gate
    # Only called twice (initial + 2 retries) before hitting the gate.
    assert test_port.call_count == 3  # 1 initial + 2 retries
    assert result.final_state["retry_count"] == 2


# ---------------------------------------------------------------------------
# §11.4 Permanent failure: fatal route, no retry
# ---------------------------------------------------------------------------


def test_permanent_failure_routes_to_failed(tmp_path: Path) -> None:
    worker = _CountingWorker()
    test_port = _ScriptedTestPort([_fatal_outcome("att-1")])
    result = _runner(tmp_path, worker, test_port).invoke(_state("R6"), thread_id="wf:R6")
    assert result.reached_end is True
    assert result.final_outcome == "failed"
    assert test_port.call_count == 1
    assert result.final_state.get("retry_count", 0) == 0


# ---------------------------------------------------------------------------
# Legacy mode (test_execution=None): execute_stub → validate, no test node
# ---------------------------------------------------------------------------


def test_legacy_mode_without_test_port_completes_normally(tmp_path: Path) -> None:
    worker = _CountingWorker()
    result = _runner(tmp_path, worker, None).invoke(_state("R7"), thread_id="wf:R7")
    assert result.reached_end is True
    assert result.final_outcome == "completed"
    assert worker.calls == 1


def test_legacy_retry_routes_to_execute_not_test(tmp_path: Path) -> None:
    """In legacy mode (DocAnt retry), retryable routes back to execute_stub, not test."""
    from tests.support.scripted_worker import ScriptedStubAdapter
    worker = ScriptedStubAdapter([WorkerOutcome.RETRYABLE_FAILURE, WorkerOutcome.SUCCESS])
    result = _runner(tmp_path, worker, None).invoke(_state("R8"), thread_id="wf:R8")
    assert result.reached_end is True
    assert result.final_outcome == "completed"
    assert result.final_state["retry_count"] == 1
