"""CP4 — context binding tests (§11.7, §2.1).

Verifies that DurableTestExecution fails closed when the context_manifest_digest from
the workflow state does not match the expected digest set at construction time.
Also verifies happy-path binding passthrough and that empty expected_digest skips check.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import RecoveryDisposition
from ant_orchestrator.integration.test_execution_adapter import DurableTestExecution


def _mock_ant(outcome: TestExecutionOutcome | None = None) -> MagicMock:
    ant = MagicMock()
    if outcome is not None:
        mock_result = MagicMock()
        mock_result.cancelled = False
        mock_result.outcome = outcome
        ant.execute.return_value = mock_result
    return ant


def _mock_attempts(attempt_id: str = "att-1") -> MagicMock:
    ao = MagicMock()
    ao.before_execute.return_value = attempt_id
    return ao


def _make_adapter(expected_digest: str = "") -> DurableTestExecution:
    success = TestExecutionOutcome(
        outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok"
    )
    return DurableTestExecution(
        ant=_mock_ant(outcome=success),
        attempt_orchestrator=_mock_attempts(),
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
        expected_context_digest=expected_digest,
    )


# ---------------------------------------------------------------------------
# Context binding: fail closed on mismatch
# ---------------------------------------------------------------------------


def test_mismatch_digest_returns_boundary_failure_without_calling_ant() -> None:
    adapter = _make_adapter(expected_digest="abc123")
    outcome = adapter.execute(
        task_id="T1", run_id="R1", context_manifest_digest="deadbeef"
    )
    assert outcome.outcome is WorkerOutcome.PERMANENT_FAILURE
    assert outcome.disposition is RecoveryDisposition.TERMINAL_FAILED
    assert "mismatch" in (outcome.attempt_ref or "")
    # Ant must NOT be called when digest fails.
    adapter._ant.execute.assert_not_called()


def test_mismatch_digest_does_not_start_attempt() -> None:
    success = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")
    ant = _mock_ant(outcome=success)
    ao = _mock_attempts()
    adapter = DurableTestExecution(
        ant=ant,
        attempt_orchestrator=ao,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
        expected_context_digest="expected-xyz",
    )
    adapter.execute(task_id="T1", run_id="R1", context_manifest_digest="wrong-xyz")
    ao.before_execute.assert_not_called()


def test_matching_digest_calls_ant_normally() -> None:
    success = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")
    ant = _mock_ant(outcome=success)
    ao = _mock_attempts()
    adapter = DurableTestExecution(
        ant=ant,
        attempt_orchestrator=ao,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
        expected_context_digest="correct-digest",
    )
    outcome = adapter.execute(
        task_id="T1", run_id="R1", context_manifest_digest="correct-digest"
    )
    assert outcome.outcome is WorkerOutcome.SUCCESS
    ant.execute.assert_called_once()


def test_empty_expected_digest_skips_check_and_calls_ant() -> None:
    adapter = _make_adapter(expected_digest="")
    outcome = adapter.execute(
        task_id="T1", run_id="R1", context_manifest_digest="any-value"
    )
    # Empty expected → no check → ant runs → success.
    assert outcome.outcome is WorkerOutcome.SUCCESS


def test_both_digests_empty_skips_check() -> None:
    adapter = _make_adapter(expected_digest="")
    outcome = adapter.execute(
        task_id="T1", run_id="R1", context_manifest_digest=""
    )
    assert outcome.outcome is WorkerOutcome.SUCCESS


# ---------------------------------------------------------------------------
# Scope digest is stable (same inputs → same digest)
# ---------------------------------------------------------------------------


def test_scope_digest_is_deterministic() -> None:
    success = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")
    a = DurableTestExecution(
        ant=_mock_ant(outcome=success),
        attempt_orchestrator=_mock_attempts(),
        canonical_read_scope=("src/", "tests/"),
        command_profile_key="pytest",
    )
    b = DurableTestExecution(
        ant=_mock_ant(outcome=success),
        attempt_orchestrator=_mock_attempts(),
        canonical_read_scope=("src/", "tests/"),
        command_profile_key="pytest",
    )
    assert a._read_scope_digest == b._read_scope_digest


def test_scope_digest_is_order_independent() -> None:
    success = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")
    a = DurableTestExecution(
        ant=_mock_ant(outcome=success),
        attempt_orchestrator=_mock_attempts(),
        canonical_read_scope=("b", "a"),
        command_profile_key="pytest",
    )
    b = DurableTestExecution(
        ant=_mock_ant(outcome=success),
        attempt_orchestrator=_mock_attempts(),
        canonical_read_scope=("a", "b"),
        command_profile_key="pytest",
    )
    assert a._read_scope_digest == b._read_scope_digest


# ---------------------------------------------------------------------------
# Invariant guards
# ---------------------------------------------------------------------------


def test_empty_canonical_read_scope_raises() -> None:
    with pytest.raises(InvariantViolation, match="read_scope"):
        DurableTestExecution(
            ant=_mock_ant(),
            attempt_orchestrator=_mock_attempts(),
            canonical_read_scope=(),
            command_profile_key="pytest",
        )


def test_missing_task_id_raises() -> None:
    adapter = _make_adapter()
    with pytest.raises(InvariantViolation, match="task_id"):
        adapter.execute(task_id="", run_id="R1")


def test_missing_run_id_raises() -> None:
    adapter = _make_adapter()
    with pytest.raises(InvariantViolation, match="task_id"):
        adapter.execute(task_id="T1", run_id="")


# ---------------------------------------------------------------------------
# Logical action id is {task_id}-test
# ---------------------------------------------------------------------------


def test_logical_action_id_uses_test_suffix() -> None:
    success = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-ok")
    ant = _mock_ant(outcome=success)
    ao = _mock_attempts()
    adapter = DurableTestExecution(
        ant=ant,
        attempt_orchestrator=ao,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    adapter.execute(task_id="MY-TASK", run_id="RUN-99")
    ao.before_execute.assert_called_once_with("RUN-99", "MY-TASK-test")


# ---------------------------------------------------------------------------
# Cancellation: out-of-band → is_cancelled property
# ---------------------------------------------------------------------------


def test_cancelled_result_maps_to_terminal_cancelled_disposition() -> None:
    cancelled_outcome = MagicMock()
    cancelled_outcome.cancelled = True
    ant = MagicMock()
    ant.execute.return_value = cancelled_outcome
    ao = _mock_attempts()
    adapter = DurableTestExecution(
        ant=ant,
        attempt_orchestrator=ao,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    outcome = adapter.execute(task_id="T1", run_id="R1")
    assert outcome.is_cancelled is True
    assert outcome.disposition is RecoveryDisposition.TERMINAL_CANCELLED
    # after_execute must NOT be called for out-of-band cancellation.
    ao.after_execute.assert_not_called()
