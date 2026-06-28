"""CP7 E2E: retry, escalation, and fatal failure scenarios (§matrix E1-E8).

E1: transient → retry once → SUCCESS → COMPLETED.
E2: retry_count increments by 1 per RETRYABLE outcome.
E3: retry exhausted → RETRY_LIMIT gate interrupt (not final).
E4: port called exactly (base_limit + 1) times before RETRY_LIMIT gate.
E5: ESCALATION (deadline exceeded) → SCOPE_CHANGE gate interrupt.
E6: isolation unavailable (ESCALATION category) → SCOPE_CHANGE gate interrupt.
E7: PERMANENT_FAILURE (deterministic) → final_outcome = "failed".
E8: unknown failure (ESCALATION, UNKNOWN reason) → SCOPE_CHANGE gate interrupt.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.config.constants import WORKFLOW_MAX_RETRIES
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from tests.support.cp7_e2e_harness import (
    THREAD_ID,
    ScriptedTestPort,
    e2e_state,
    make_runner,
)

# ---------------------------------------------------------------------------
# Outcome factories
# ---------------------------------------------------------------------------


def _success() -> TestExecutionOutcome:
    return TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")


def _retryable() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.RETRYABLE_FAILURE,
        attempt_ref="att-r",
        disposition=RecoveryDisposition.RETRY,
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        category=FailureCategory.TRANSIENT_INTERRUPTION,
    )


def _deadline_escalation() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="att-dl",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.TEST_DEADLINE_EXCEEDED,
        category=FailureCategory.TEST_DEADLINE_EXCEEDED,
    )


def _isolation_unavailable() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="att-iu",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE,
        category=FailureCategory.EXECUTION_ISOLATION_UNAVAILABLE,
    )


def _fatal() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.PERMANENT_FAILURE,
        attempt_ref="att-f",
        disposition=RecoveryDisposition.TERMINAL_FAILED,
        reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
        category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
    )


def _unknown_escalation() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="att-u",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.UNKNOWN_FAILURE,
        category=FailureCategory.UNKNOWN,
    )


# ---------------------------------------------------------------------------
# E1-E2: transient retry path
# ---------------------------------------------------------------------------


def test_transient_retry_then_pass(tmp_path: Path) -> None:
    """E1: RETRYABLE → retry once → SUCCESS → COMPLETED."""
    port = ScriptedTestPort([_retryable(), _success()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "completed"
    assert port.calls == 2


def test_retry_increments_retry_count(tmp_path: Path) -> None:
    """E2: retry_count = 1 after one RETRYABLE → SUCCESS."""
    port = ScriptedTestPort([_retryable(), _success()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_state.get("retry_count", 0) == 1


# ---------------------------------------------------------------------------
# E3-E4: retry exhausted → RETRY_LIMIT gate interrupt
# ---------------------------------------------------------------------------


def test_retry_exhausted_produces_interrupt(tmp_path: Path) -> None:
    """E3: RETRYABLE × (limit+1) → RETRY_LIMIT gate interrupt (not final)."""
    port = ScriptedTestPort([_retryable()] * (WORKFLOW_MAX_RETRIES + 1))
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.reached_end is False
    assert result.interrupt is not None
    assert result.final_outcome is None


def test_retry_exhausted_port_call_count(tmp_path: Path) -> None:
    """E4: port called exactly (base_limit + 1) times before RETRY_LIMIT gate."""
    port = ScriptedTestPort([_retryable()] * (WORKFLOW_MAX_RETRIES + 2))
    runner = make_runner(tmp_path, test_execution=port)
    runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert port.calls == WORKFLOW_MAX_RETRIES + 1


# ---------------------------------------------------------------------------
# E5-E6: escalation → SCOPE_CHANGE gate interrupt
# ---------------------------------------------------------------------------


def test_deadline_escalation_produces_scope_change_interrupt(tmp_path: Path) -> None:
    """E5: TEST_DEADLINE_EXCEEDED (ESCALATION) → SCOPE_CHANGE gate interrupt."""
    port = ScriptedTestPort([_deadline_escalation()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.reached_end is False
    assert result.interrupt is not None


def test_isolation_unavailable_escalates(tmp_path: Path) -> None:
    """E6: EXECUTION_ISOLATION_UNAVAILABLE → SCOPE_CHANGE gate interrupt."""
    port = ScriptedTestPort([_isolation_unavailable()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.reached_end is False
    assert result.interrupt is not None


# ---------------------------------------------------------------------------
# E7: fatal → PHASE_FAILED
# ---------------------------------------------------------------------------


def test_fatal_failure_routes_to_failed(tmp_path: Path) -> None:
    """E7: PERMANENT_FAILURE (deterministic) → final_outcome = "failed"."""
    port = ScriptedTestPort([_fatal()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "failed"
    assert result.reached_end is True
    assert result.final_state.get("test_status") == "fatal"


# ---------------------------------------------------------------------------
# E8: unknown failure → SCOPE_CHANGE gate (fail-safe escalation)
# ---------------------------------------------------------------------------


def test_unknown_failure_escalates(tmp_path: Path) -> None:
    """E8: UNKNOWN_FAILURE (ESCALATION) → SCOPE_CHANGE gate interrupt."""
    port = ScriptedTestPort([_unknown_escalation()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.reached_end is False
    assert result.interrupt is not None
    assert result.final_outcome is None
