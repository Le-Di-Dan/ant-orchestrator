"""Deterministic Test Ant failure classifier (PHASE_6_PLAN CP3, §5/§F).

Pure and deterministic: it consumes only typed *system facts* (:class:`TestExecutionFacts`)
— never a raw exception, traceback, provider output, host path or unbounded stdout — and
returns a :class:`ClassifiedExecution` (test result + process status + optional
:class:`FailureClassification` + bounded diagnostic hint). The canonical category →
(transience, disposition, reason) mapping lives in the CP1 ``test_failure_policy`` so this
module never re-decides retryability; it only selects a category from the facts.

Exhaustive: every CP2 ``IsolatedRunStatus`` is handled by an explicit branch. An unmapped
status raises :class:`InvariantViolation` (a programmer invariant), so adding a status
without a rule makes the exhaustiveness test fail rather than silently degrading to UNKNOWN.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.application.ports.test_isolation import IsolatedRunStatus
from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    FailureClassification,
    TestReasonCode,
)
from ant_orchestrator.core.domain.test_failure_policy import (
    cancellation_classification,
    default_classification,
)
from ant_orchestrator.workers.test.provisioning import CleanupStatus, SnapshotProvisionStatus
from ant_orchestrator.workers.test.pytest_outcome import is_interrupted_exit, result_for_exit_code
from ant_orchestrator.workers.test.report import TestProcessStatus, TestResult

_FC = FailureCategory
_PS = TestProcessStatus


class PreflightStatus(_StrEnum):
    """Worker-level fail-closed gate evaluated BEFORE any backend run."""

    OK = "ok"
    IDENTITY_MISMATCH = "identity_mismatch"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    SCOPE_VIOLATION = "scope_violation"
    COMMAND_POLICY_DENIED = "command_policy_denied"
    INVALID_COMMAND = "invalid_command"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"


class BackendReason(_StrEnum):
    """Stable, allowlisted refinement of a failed launch/setup (never parsed from text)."""

    EXECUTABLE_MISSING = "executable_missing"
    PERMISSION_DENIED = "permission_denied"
    ADAPTER_CONFIG_INVALID = "adapter_config_invalid"
    RESOURCE_TEMPORARILY_UNAVAILABLE = "resource_temporarily_unavailable"
    PROCESS_INTERRUPTION = "process_interruption"
    ISOLATION_VIOLATION = "isolation_violation"


@dataclass(frozen=True, slots=True)
class TestExecutionFacts:
    """The complete, typed fact set the classifier is allowed to observe."""

    __test__ = False  # domain term; not a pytest test class

    preflight: PreflightStatus = PreflightStatus.OK
    capability_available: bool = True
    snapshot: SnapshotProvisionStatus = SnapshotProvisionStatus.BUILT_VERIFIED
    run_status: IsolatedRunStatus | None = None
    exit_code: int | None = None
    backend_reason: BackendReason | None = None
    cleanup: CleanupStatus = CleanupStatus.CLEAN
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    detail_code: str | None = None


@dataclass(frozen=True, slots=True)
class ClassifiedExecution:
    """The deterministic verdict: result + process status + classification + hint."""

    __test__ = False  # domain term; not a pytest test class

    test_result: TestResult
    process_status: TestProcessStatus
    classification: FailureClassification | None
    diagnostic_hint: str

    @property
    def is_success(self) -> bool:
        return self.classification is None


# Backend-reason refinement for a failed launch/setup (deterministic, allowlisted only).
_BACKEND_CATEGORY: dict[BackendReason, FailureCategory] = {
    BackendReason.EXECUTABLE_MISSING: _FC.EXECUTABLE_MISSING,
    BackendReason.PERMISSION_DENIED: _FC.PERMISSION_DENIED,
    BackendReason.ADAPTER_CONFIG_INVALID: _FC.ADAPTER_CONFIG_INVALID,
    BackendReason.RESOURCE_TEMPORARILY_UNAVAILABLE: _FC.ADAPTER_TRANSIENT,
    BackendReason.PROCESS_INTERRUPTION: _FC.TRANSIENT_INTERRUPTION,
    BackendReason.ISOLATION_VIOLATION: _FC.ISOLATION_VIOLATION,
}

_PREFLIGHT_CATEGORY: dict[PreflightStatus, FailureCategory] = {
    PreflightStatus.IDENTITY_MISMATCH: _FC.EXECUTION_BOUNDARY_FAILURE,
    PreflightStatus.CONTEXT_UNAVAILABLE: _FC.EXECUTION_BOUNDARY_FAILURE,
    PreflightStatus.SCOPE_VIOLATION: _FC.EXECUTION_BOUNDARY_FAILURE,
    PreflightStatus.COMMAND_POLICY_DENIED: _FC.POLICY_VIOLATION,
    PreflightStatus.INVALID_COMMAND: _FC.INVALID_COMMAND,
    PreflightStatus.BUDGET_EXHAUSTED: _FC.BUDGET_EXHAUSTED,
}

# Bounded, deterministic, LLM-free hints keyed by stable reason code.
_PASS_HINT = "Acceptance suite passed; no Queen review is required."
_HINTS: dict[TestReasonCode, str] = {
    TestReasonCode.DETERMINISTIC_TEST_FAILURE: (
        "Acceptance suite reported deterministic test failures; Queen review is required."
    ),
    TestReasonCode.TEST_DEADLINE_EXCEEDED: (
        "Execution exceeded the approved deadline; same-strategy retry is not permitted "
        "without transient evidence."
    ),
    TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE: (
        "Isolation backend is unavailable; execution was not started on the host."
    ),
    TestReasonCode.ISOLATION_SETUP_FAILED: (
        "Isolation setup failed; execution was not started and no host fallback is used."
    ),
    TestReasonCode.ISOLATION_VIOLATION: (
        "An execution-isolation invariant was violated; the result is fail-closed."
    ),
    TestReasonCode.EXECUTION_BOUNDARY_DENIED: (
        "Execution boundary or identity check failed; the run was denied before launch."
    ),
    TestReasonCode.COMMAND_POLICY_DENIED: (
        "The requested command was denied by policy; the backend was not invoked."
    ),
    TestReasonCode.INVALID_COMMAND: (
        "The requested command is invalid; the backend was not invoked."
    ),
    TestReasonCode.EXECUTABLE_MISSING: (
        "The test executable was missing; this is a permanent failure."
    ),
    TestReasonCode.PERMISSION_DENIED: (
        "Permission was denied launching the run; this is permanent."
    ),
    TestReasonCode.INVALID_ADAPTER_CONFIGURATION: (
        "The isolation adapter configuration is invalid; this is a permanent failure."
    ),
    TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED: (
        "An audited process interruption occurred; a bounded same-worker retry is permitted."
    ),
    TestReasonCode.ADAPTER_TEMPORARILY_UNAVAILABLE: (
        "The adapter was temporarily unavailable (allowlisted); a bounded retry is permitted."
    ),
    TestReasonCode.BUDGET_EXHAUSTED: "The execution budget is exhausted; escalation is required.",
    TestReasonCode.EXECUTION_CANCELLED: (
        "Execution was cancelled; no retry or regroup is performed."
    ),
    TestReasonCode.UNKNOWN_FAILURE: (
        "An unrecognized failure occurred; safe escalation is required."
    ),
}


class TestFailureClassifier:
    """Pure, deterministic classifier. No I/O, no LLM, no raw exception input."""

    __test__ = False  # domain term; not a pytest test class

    def classify(self, facts: TestExecutionFacts) -> ClassifiedExecution:
        """Return the deterministic verdict for a complete fact set."""
        verdict = self._decide(facts)
        # A cleanup failure with security impact can never be a silent success: a lingering
        # isolation resource is a containment violation (§12), so a pass is downgraded.
        if facts.cleanup is CleanupStatus.FAILED_SECURITY_IMPACT and verdict.is_success:
            return self._failure(_FC.ISOLATION_VIOLATION, _PS.COMPLETED, facts)
        return verdict

    def _decide(self, facts: TestExecutionFacts) -> ClassifiedExecution:
        if facts.preflight is not PreflightStatus.OK:
            return self._preflight(facts)
        if not facts.capability_available:
            return self._failure(
                _FC.EXECUTION_ISOLATION_UNAVAILABLE, _PS.ISOLATION_UNAVAILABLE, facts
            )
        if facts.snapshot is SnapshotProvisionStatus.INTEGRITY_MISMATCH:
            return self._failure(_FC.ISOLATION_VIOLATION, _PS.ISOLATION_SETUP_FAILED, facts)
        if facts.snapshot is SnapshotProvisionStatus.SETUP_FAILED:
            return self._failure(_FC.ISOLATION_SETUP_FAILURE, _PS.ISOLATION_SETUP_FAILED, facts)
        return self._classify_run(facts)

    # --- pre-execution gate --------------------------------------------------
    def _preflight(self, facts: TestExecutionFacts) -> ClassifiedExecution:
        if facts.preflight is PreflightStatus.CANCELLED:
            return self._cancelled(facts, _PS.CANCELLED)
        category = _PREFLIGHT_CATEGORY[facts.preflight]
        return self._failure(category, _PS.LAUNCH_FAILED, facts)

    # --- backend run ---------------------------------------------------------
    def _classify_run(self, facts: TestExecutionFacts) -> ClassifiedExecution:
        status = facts.run_status
        if status is IsolatedRunStatus.COMPLETED:
            return self._completed(facts)
        if status is IsolatedRunStatus.TIMEOUT:
            return self._failure(_FC.TEST_DEADLINE_EXCEEDED, _PS.TIMEOUT, facts)
        if status is IsolatedRunStatus.CANCELLED:
            return self._cancelled(facts, _PS.CANCELLED)
        if status is IsolatedRunStatus.ISOLATION_UNAVAILABLE:
            return self._failure(
                _FC.EXECUTION_ISOLATION_UNAVAILABLE, _PS.ISOLATION_UNAVAILABLE, facts
            )
        if status is IsolatedRunStatus.ISOLATION_SETUP_FAILED:
            category = self._refine(facts.backend_reason, _FC.ISOLATION_SETUP_FAILURE)
            return self._failure(category, _PS.ISOLATION_SETUP_FAILED, facts)
        if status is IsolatedRunStatus.LAUNCH_FAILED:
            category = self._refine(facts.backend_reason, _FC.ISOLATION_SETUP_FAILURE)
            return self._failure(category, _PS.LAUNCH_FAILED, facts)
        raise InvariantViolation(  # exhaustiveness guard — no silent UNKNOWN fallthrough
            f"unmapped IsolatedRunStatus {status!r} in TestFailureClassifier"
        )

    def _completed(self, facts: TestExecutionFacts) -> ClassifiedExecution:
        result = result_for_exit_code(facts.exit_code)
        if result is TestResult.PASSED:
            return ClassifiedExecution(result, _PS.COMPLETED, None, _PASS_HINT)
        if result is TestResult.FAILED:
            return self._failure(
                _FC.DETERMINISTIC_TEST_FAILURE, _PS.COMPLETED, facts, result=result
            )
        if result is TestResult.NO_TESTS:
            return self._failure(
                _FC.UNKNOWN, _PS.COMPLETED, facts, result=result, detail="no_tests_collected"
            )
        process = _PS.INTERRUPTED if is_interrupted_exit(facts.exit_code) else _PS.COMPLETED
        category = _FC.ADAPTER_CONFIG_INVALID if facts.exit_code == 4 else _FC.UNKNOWN
        return self._failure(category, process, facts, result=result)

    # --- builders ------------------------------------------------------------
    def _failure(
        self,
        category: FailureCategory,
        process_status: TestProcessStatus,
        facts: TestExecutionFacts,
        *,
        result: TestResult = TestResult.ERROR,
        detail: str | None = None,
    ) -> ClassifiedExecution:
        classification = default_classification(
            category, evidence_refs=facts.evidence_refs, detail_code=detail or facts.detail_code
        )
        hint = _HINTS[classification.reason_code]
        return ClassifiedExecution(result, process_status, classification, hint)

    def _cancelled(
        self, facts: TestExecutionFacts, process_status: TestProcessStatus
    ) -> ClassifiedExecution:
        classification = cancellation_classification(
            evidence_refs=facts.evidence_refs, detail_code=facts.detail_code
        )
        return ClassifiedExecution(
            TestResult.ERROR, process_status, classification, _HINTS[classification.reason_code]
        )

    @staticmethod
    def _refine(backend_reason: BackendReason | None, default: FailureCategory) -> FailureCategory:
        if backend_reason is None:
            return default
        return _BACKEND_CATEGORY[backend_reason]
