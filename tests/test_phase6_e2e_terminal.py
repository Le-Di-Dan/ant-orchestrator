"""CP7 E2E: cancellation, rejection, and approval-gate scenarios (§matrix T1-T6).

T1: port returns TERMINAL_CANCELLED → final_outcome = "cancelled".
T2: cancel probe fires at test node → CANCELLED, backend not called.
T3: SCOPE_CHANGE gate → reject → final_outcome = "rejected".
T4: SCOPE_CHANGE gate → approve REPLAN → graph re-runs → COMPLETED.
T5: SCOPE_CHANGE gate result is not final (interrupt still pending).
T6: cancellation probe fires before test node → port NOT called.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
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


def _cancelled() -> TestExecutionOutcome:
    """Out-of-band cancellation: TERMINAL_CANCELLED disposition."""
    return TestExecutionOutcome(
        outcome=WorkerOutcome.PERMANENT_FAILURE,
        attempt_ref="att-c",
        disposition=RecoveryDisposition.TERMINAL_CANCELLED,
        reason_code=TestReasonCode.EXECUTION_CANCELLED,
        category=FailureCategory.UNKNOWN,
    )


def _escalation() -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="att-e",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.TEST_DEADLINE_EXCEEDED,
        category=FailureCategory.TEST_DEADLINE_EXCEEDED,
    )


# ---------------------------------------------------------------------------
# Cancel probes
# ---------------------------------------------------------------------------


class _AlwaysCancelProbe:
    def is_cancel_requested(self, run_id: str) -> bool:
        return True


class _CancelAfterN:
    """Fires True after N invocations (lets first N graph nodes pass)."""

    def __init__(self, fire_after: int) -> None:
        self._fire_after = fire_after
        self._calls = 0

    def is_cancel_requested(self, run_id: str) -> bool:
        self._calls += 1
        return self._calls > self._fire_after


# ---------------------------------------------------------------------------
# T1: cancellation via port TERMINAL_CANCELLED disposition
# ---------------------------------------------------------------------------


def test_cancelled_outcome_routes_to_cancelled(tmp_path: Path) -> None:
    """T1: port returns TERMINAL_CANCELLED → final_outcome = "cancelled"."""
    port = ScriptedTestPort([_cancelled()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "cancelled"
    assert result.reached_end is True


# ---------------------------------------------------------------------------
# T2: cancel probe fires at test node → CANCELLED, backend not called
# ---------------------------------------------------------------------------


def test_cancel_probe_at_test_node_cancels_without_backend(tmp_path: Path) -> None:
    """T2: probe fires at test node boundary → CANCELLED, port NOT called.

    Probe checked at execute_stub (call 1) and test (call 2).
    fire_after=1: execute_stub proceeds, test node sees cancel → CANCELLED before port.
    """
    port = ScriptedTestPort([_success()])
    probe = _CancelAfterN(fire_after=1)
    runner = make_runner(tmp_path, test_execution=port, cancellation_probe=probe)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "cancelled"
    assert port.calls == 0


# ---------------------------------------------------------------------------
# T3: SCOPE_CHANGE gate → reject → REJECTED
# ---------------------------------------------------------------------------


def test_scope_change_gate_reject_routes_to_rejected(tmp_path: Path) -> None:
    """T3: escalation → SCOPE_CHANGE gate → reject → final_outcome = "rejected"."""
    port = ScriptedTestPort([_escalation()])
    runner = make_runner(tmp_path, test_execution=port)

    invoke_result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert invoke_result.interrupt is not None

    resume_result = runner.resume(
        thread_id=THREAD_ID,
        interrupt_id=invoke_result.interrupt.langgraph_interrupt_id,
        decision="rejected",
    )
    assert resume_result.final_outcome == "rejected"
    assert resume_result.reached_end is True


# ---------------------------------------------------------------------------
# T4: SCOPE_CHANGE gate → approve REPLAN → graph re-runs → COMPLETED
# ---------------------------------------------------------------------------


def test_scope_change_gate_approve_replan_then_pass(tmp_path: Path) -> None:
    """T4: escalation → approve REPLAN → graph re-runs → final_outcome = "completed"."""
    port = ScriptedTestPort([_escalation(), _success()])
    runner = make_runner(tmp_path, test_execution=port)

    invoke_result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert invoke_result.interrupt is not None

    resume_result = runner.resume(
        thread_id=THREAD_ID,
        interrupt_id=invoke_result.interrupt.langgraph_interrupt_id,
        decision="approved",
    )
    assert resume_result.final_outcome == "completed"
    assert port.calls == 2  # first call failed, second passed after REPLAN


# ---------------------------------------------------------------------------
# T5: SCOPE_CHANGE gate result is not final (interrupt still pending)
# ---------------------------------------------------------------------------


def test_scope_change_gate_not_final_before_approval(tmp_path: Path) -> None:
    """T5: escalation → SCOPE_CHANGE gate → NOT final, interrupt present."""
    port = ScriptedTestPort([_escalation()])
    runner = make_runner(tmp_path, test_execution=port)
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.reached_end is False
    assert result.final_outcome is None
    assert result.interrupt is not None


# ---------------------------------------------------------------------------
# T6: AlwaysCancelProbe — cancel before test node, port not called
# ---------------------------------------------------------------------------


def test_always_cancel_probe_port_never_called(tmp_path: Path) -> None:
    """T6: probe always fires → port never called, CANCELLED immediately."""
    port = ScriptedTestPort([_success()])
    runner = make_runner(tmp_path, test_execution=port, cancellation_probe=_AlwaysCancelProbe())
    result = runner.invoke(e2e_state(), thread_id=THREAD_ID)
    assert result.final_outcome == "cancelled"
    assert port.calls == 0
