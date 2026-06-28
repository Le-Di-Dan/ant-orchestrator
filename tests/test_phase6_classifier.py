"""CP3 — deterministic TestFailureClassifier decision table (no Docker, §5/§F)."""

from __future__ import annotations

from typing import Any

from ant_orchestrator.application.ports.test_isolation import IsolatedRunStatus
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    Transience,
)
from ant_orchestrator.workers.test.classifier import (
    BackendReason,
    PreflightStatus,
    TestExecutionFacts,
    TestFailureClassifier,
)
from ant_orchestrator.workers.test.provisioning import CleanupStatus, SnapshotProvisionStatus
from ant_orchestrator.workers.test.report import TestProcessStatus, TestResult

_C = TestFailureClassifier()
_FC = FailureCategory
_D = RecoveryDisposition
_T = Transience


def _facts(**over: Any) -> TestExecutionFacts:
    base: dict[str, Any] = dict(run_status=IsolatedRunStatus.COMPLETED, exit_code=0)
    base.update(over)
    return TestExecutionFacts(**base)


def _assert(
    verdict: Any, category: FailureCategory, transience: Transience, disp: RecoveryDisposition
) -> None:
    assert verdict.classification is not None
    assert verdict.classification.category is category
    assert verdict.classification.transience is transience
    assert verdict.classification.recommended_disposition is disp


def test_pass() -> None:
    verdict = _C.classify(_facts(exit_code=0))
    assert verdict.is_success
    assert verdict.classification is None
    assert verdict.test_result is TestResult.PASSED
    assert verdict.process_status is TestProcessStatus.COMPLETED


def test_deterministic_test_failure() -> None:
    verdict = _C.classify(_facts(exit_code=1))
    _assert(verdict, _FC.DETERMINISTIC_TEST_FAILURE, _T.DETERMINISTIC, _D.ESCALATE)
    assert verdict.test_result is TestResult.FAILED
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_audited_transient_interruption_retries() -> None:
    verdict = _C.classify(
        _facts(
            run_status=IsolatedRunStatus.LAUNCH_FAILED,
            exit_code=None,
            backend_reason=BackendReason.PROCESS_INTERRUPTION,
        )
    )
    _assert(verdict, _FC.TRANSIENT_INTERRUPTION, _T.TRANSIENT, _D.RETRY)
    assert verdict.classification is not None and verdict.classification.is_retryable


def test_adapter_temporarily_unavailable_retries() -> None:
    verdict = _C.classify(
        _facts(
            run_status=IsolatedRunStatus.LAUNCH_FAILED,
            exit_code=None,
            backend_reason=BackendReason.RESOURCE_TEMPORARILY_UNAVAILABLE,
        )
    )
    _assert(verdict, _FC.ADAPTER_TRANSIENT, _T.TRANSIENT, _D.RETRY)


def test_plain_deadline_does_not_retry() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.TIMEOUT, exit_code=None))
    _assert(verdict, _FC.TEST_DEADLINE_EXCEEDED, _T.UNKNOWN, _D.ESCALATE)
    assert verdict.process_status is TestProcessStatus.TIMEOUT
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_executable_missing_is_terminal() -> None:
    verdict = _C.classify(
        _facts(
            run_status=IsolatedRunStatus.LAUNCH_FAILED,
            exit_code=None,
            backend_reason=BackendReason.EXECUTABLE_MISSING,
        )
    )
    _assert(verdict, _FC.EXECUTABLE_MISSING, _T.DETERMINISTIC, _D.TERMINAL_FAILED)


def test_permission_denied_is_terminal() -> None:
    verdict = _C.classify(
        _facts(
            run_status=IsolatedRunStatus.LAUNCH_FAILED,
            exit_code=None,
            backend_reason=BackendReason.PERMISSION_DENIED,
        )
    )
    _assert(verdict, _FC.PERMISSION_DENIED, _T.DETERMINISTIC, _D.TERMINAL_FAILED)


def test_adapter_config_invalid_is_terminal() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.COMPLETED, exit_code=4))
    _assert(verdict, _FC.ADAPTER_CONFIG_INVALID, _T.DETERMINISTIC, _D.TERMINAL_FAILED)
    assert verdict.process_status is TestProcessStatus.COMPLETED


def test_policy_denial_is_terminal_and_not_executed() -> None:
    verdict = _C.classify(TestExecutionFacts(preflight=PreflightStatus.COMMAND_POLICY_DENIED))
    _assert(verdict, _FC.POLICY_VIOLATION, _T.DETERMINISTIC, _D.TERMINAL_FAILED)
    assert verdict.process_status is TestProcessStatus.LAUNCH_FAILED


def test_invalid_command_is_terminal() -> None:
    verdict = _C.classify(TestExecutionFacts(preflight=PreflightStatus.INVALID_COMMAND))
    _assert(verdict, _FC.INVALID_COMMAND, _T.DETERMINISTIC, _D.TERMINAL_FAILED)


def test_execution_boundary_violation_is_terminal() -> None:
    verdict = _C.classify(TestExecutionFacts(preflight=PreflightStatus.IDENTITY_MISMATCH))
    _assert(verdict, _FC.EXECUTION_BOUNDARY_FAILURE, _T.DETERMINISTIC, _D.TERMINAL_FAILED)
    verdict2 = _C.classify(TestExecutionFacts(preflight=PreflightStatus.SCOPE_VIOLATION))
    _assert(verdict2, _FC.EXECUTION_BOUNDARY_FAILURE, _T.DETERMINISTIC, _D.TERMINAL_FAILED)


def test_isolation_backend_unavailable_fail_closed() -> None:
    verdict = _C.classify(TestExecutionFacts(capability_available=False))
    _assert(verdict, _FC.EXECUTION_ISOLATION_UNAVAILABLE, _T.DETERMINISTIC, _D.ESCALATE)
    assert verdict.process_status is TestProcessStatus.ISOLATION_UNAVAILABLE
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_isolation_setup_failure_not_blind_retry() -> None:
    verdict = _C.classify(TestExecutionFacts(snapshot=SnapshotProvisionStatus.SETUP_FAILED))
    _assert(verdict, _FC.ISOLATION_SETUP_FAILURE, _T.DETERMINISTIC, _D.ESCALATE)
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_isolation_violation_terminal_with_evidence() -> None:
    verdict = _C.classify(
        TestExecutionFacts(
            snapshot=SnapshotProvisionStatus.INTEGRITY_MISMATCH, evidence_refs=("audit:x",)
        )
    )
    _assert(verdict, _FC.ISOLATION_VIOLATION, _T.DETERMINISTIC, _D.TERMINAL_FAILED)
    assert verdict.classification is not None
    assert verdict.classification.evidence.evidence_refs == ("audit:x",)


def test_budget_exhausted_escalates() -> None:
    verdict = _C.classify(TestExecutionFacts(preflight=PreflightStatus.BUDGET_EXHAUSTED))
    _assert(verdict, _FC.BUDGET_EXHAUSTED, _T.DETERMINISTIC, _D.ESCALATE)


def test_unknown_is_safe_escalation() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.COMPLETED, exit_code=3))
    _assert(verdict, _FC.UNKNOWN, _T.UNKNOWN, _D.ESCALATE)
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_no_tests_is_not_pass() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.COMPLETED, exit_code=5))
    assert verdict.test_result is TestResult.NO_TESTS
    assert not verdict.is_success
    assert verdict.classification is not None and not verdict.classification.is_retryable


def test_interrupted_exit_marks_process_interrupted() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.COMPLETED, exit_code=2))
    assert verdict.process_status is TestProcessStatus.INTERRUPTED
    assert verdict.test_result is TestResult.ERROR


def test_cancellation_is_terminal_cancelled() -> None:
    verdict = _C.classify(_facts(run_status=IsolatedRunStatus.CANCELLED, exit_code=None))
    assert verdict.classification is not None
    assert verdict.classification.recommended_disposition is _D.TERMINAL_CANCELLED
    assert verdict.process_status is TestProcessStatus.CANCELLED


def test_cleanup_security_impact_overrides_pass() -> None:
    verdict = _C.classify(_facts(exit_code=0, cleanup=CleanupStatus.FAILED_SECURITY_IMPACT))
    assert not verdict.is_success
    _assert(verdict, _FC.ISOLATION_VIOLATION, _T.DETERMINISTIC, _D.TERMINAL_FAILED)


def test_plain_cleanup_failure_does_not_change_pass() -> None:
    verdict = _C.classify(_facts(exit_code=0, cleanup=CleanupStatus.FAILED))
    assert verdict.is_success


def test_exhaustive_isolated_run_status_mapping() -> None:
    # Every CP2 IsolatedRunStatus must classify without raising / silent UNKNOWN fallthrough.
    for status in IsolatedRunStatus:
        verdict = _C.classify(_facts(run_status=status, exit_code=0))
        assert verdict.process_status in TestProcessStatus
        if status is not IsolatedRunStatus.COMPLETED:
            assert verdict.classification is not None
