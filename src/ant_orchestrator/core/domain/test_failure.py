"""Test Ant failure taxonomy and classification model (PHASE_6_PLAN CP1, §E/§F).

Pure domain: enums whose ``value`` is the stable string persisted in graph state,
evidence, audit and durable payloads, plus the immutable ``FailureClassification``
the Test Ant emits. No I/O, no infrastructure, no raw exception/output/host path —
classification carries only bounded, sanitized references.

Disposition is split from category and transience on purpose: a category names *what*
failed, transience names *whether* a retry could ever help, and the recommended
disposition names *what the workflow should do*. The canonical category → disposition
policy lives in :mod:`ant_orchestrator.core.domain.test_failure_policy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation

# Bounds on the sanitized evidence a classification may carry (no raw output/secrets).
MAX_EVIDENCE_REFS = 16
MAX_EVIDENCE_REF_CHARS = 200
MAX_DETAIL_CODE_CHARS = 120


class FailureCategory(_StrEnum):
    """What kind of failure the Test Ant observed (PHASE_6_PLAN §E).

    A category names the failure; it does NOT by itself decide retryability. A single
    generic ``TIMEOUT`` category that defaults to retry is deliberately absent:
    ``TEST_DEADLINE_EXCEEDED`` is its own category and is never transient by default.
    """

    TRANSIENT_INTERRUPTION = "transient_interruption"
    ADAPTER_TRANSIENT = "adapter_transient"
    TEST_DEADLINE_EXCEEDED = "test_deadline_exceeded"
    EXECUTABLE_MISSING = "executable_missing"
    PERMISSION_DENIED = "permission_denied"
    ADAPTER_CONFIG_INVALID = "adapter_config_invalid"
    DETERMINISTIC_TEST_FAILURE = "deterministic_test_failure"
    POLICY_VIOLATION = "policy_violation"
    INVALID_COMMAND = "invalid_command"
    EXECUTION_BOUNDARY_FAILURE = "execution_boundary_failure"
    ISOLATION_VIOLATION = "isolation_violation"
    EXECUTION_ISOLATION_UNAVAILABLE = "execution_isolation_unavailable"
    ISOLATION_SETUP_FAILURE = "isolation_setup_failure"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN = "unknown"


class Transience(_StrEnum):
    """Whether a retry of the same worker + strategy could ever help (PHASE_6_PLAN §F).

    Decoupled from :class:`FailureCategory`. Only ``TRANSIENT`` may justify a retry;
    ``UNKNOWN`` is fail-safe (escalate, never blind-retry).
    """

    TRANSIENT = "transient"
    DETERMINISTIC = "deterministic"
    UNKNOWN = "unknown"


class RecoveryDisposition(_StrEnum):
    """What the workflow should do about a classified failure (PHASE_6_PLAN §F).

    The Test Ant only *recommends* a disposition; the workflow routing layer (CP4)
    enforces limits and gates. ``RETRY`` re-runs the SAME Test Ant; ``REGROUP_REQUIRED``
    is Queen-gated; ``TERMINAL_*`` are end states.
    """

    RETRY = "retry"
    REGROUP_REQUIRED = "regroup_required"
    ESCALATE = "escalate"
    TERMINAL_FAILED = "terminal_failed"
    TERMINAL_CANCELLED = "terminal_cancelled"


class TransientSignal(_StrEnum):
    """The audited/allowlisted evidence that justifies a ``TRANSIENT`` classification.

    A classification may only be ``TRANSIENT`` if it carries one of these signals, so a
    retry can never be claimed without an explicit, auditable reason.
    """

    PROCESS_INTERRUPTION = "process_interruption"
    ADAPTER_RESOURCE_UNAVAILABLE = "adapter_resource_unavailable"


class TestReasonCode(_StrEnum):
    """Stable, audit-grade reason code for a Test Ant outcome (PHASE_6_PLAN §E).

    Values are stable strings safe for audit, evidence, handoff and durable state. They
    do not depend on Python class/member names and must never be reused across meanings.
    """

    __test__ = False  # domain term; not a pytest test class

    TRANSIENT_INTERRUPTION_AUDITED = "transient_interruption_audited"
    ADAPTER_TEMPORARILY_UNAVAILABLE = "adapter_temporarily_unavailable"
    TEST_DEADLINE_EXCEEDED = "test_deadline_exceeded"
    EXECUTABLE_MISSING = "executable_missing"
    PERMISSION_DENIED = "permission_denied"
    INVALID_ADAPTER_CONFIGURATION = "invalid_adapter_configuration"
    DETERMINISTIC_TEST_FAILURE = "deterministic_test_failure"
    COMMAND_POLICY_DENIED = "command_policy_denied"
    INVALID_COMMAND = "invalid_command"
    EXECUTION_BOUNDARY_DENIED = "execution_boundary_denied"
    ISOLATION_VIOLATION = "isolation_violation"
    EXECUTION_ISOLATION_UNAVAILABLE = "execution_isolation_unavailable"
    ISOLATION_SETUP_FAILED = "isolation_setup_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    UNKNOWN_FAILURE = "unknown_failure"
    EXECUTION_CANCELLED = "execution_cancelled"


@dataclass(frozen=True, slots=True)
class FailureEvidence:
    """Bounded, sanitized evidence backing a classification (PHASE_6_PLAN §J).

    Only typed/bounded references are allowed by construction: no raw exception, no
    stdout/stderr, no provider response, no host absolute path. ``evidence_refs`` are
    short sanitized identifiers (e.g. audit ids); ``detail_code`` is a short stable code,
    never free-form output.
    """

    evidence_refs: tuple[str, ...] = ()
    transient_signal: TransientSignal | None = None
    detail_code: str | None = None

    def __post_init__(self) -> None:
        if len(self.evidence_refs) > MAX_EVIDENCE_REFS:
            raise InvariantViolation("FailureEvidence.evidence_refs exceeds the bound")
        for ref in self.evidence_refs:
            if not ref:
                raise InvariantViolation("FailureEvidence.evidence_refs entry must be non-empty")
            if len(ref) > MAX_EVIDENCE_REF_CHARS or "\n" in ref or "\r" in ref:
                raise InvariantViolation("FailureEvidence.evidence_refs entry is not a safe ref")
        if self.detail_code is not None:
            if not self.detail_code:
                raise InvariantViolation("FailureEvidence.detail_code must be non-empty if set")
            if (
                len(self.detail_code) > MAX_DETAIL_CODE_CHARS
                or "\n" in self.detail_code
                or "\r" in self.detail_code
            ):
                raise InvariantViolation("FailureEvidence.detail_code is not a safe code")

    @property
    def has_transient_signal(self) -> bool:
        """True when an audited/allowlisted transient signal is present."""
        return self.transient_signal is not None

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict for graph state / audit / handoff."""
        return {
            "evidence_refs": list(self.evidence_refs),
            "transient_signal": self.transient_signal.value if self.transient_signal else None,
            "detail_code": self.detail_code,
        }


@dataclass(frozen=True, slots=True)
class FailureClassification:
    """Immutable, fail-closed classification of a single Test Ant failure.

    Invariants (enforced here, not merely policy):

    * ``RETRY`` is valid only for ``Transience.TRANSIENT``.
    * ``TRANSIENT`` requires an audited/allowlisted ``transient_signal`` in the evidence
      (a retry can never be claimed without explicit evidence).
    * ``TERMINAL_CANCELLED`` is reserved for the cancellation reason and is never transient.
    """

    category: FailureCategory
    reason_code: TestReasonCode
    transience: Transience
    recommended_disposition: RecoveryDisposition
    evidence: FailureEvidence = field(default_factory=FailureEvidence)

    def __post_init__(self) -> None:
        if self.recommended_disposition is RecoveryDisposition.RETRY:
            if self.transience is not Transience.TRANSIENT:
                raise InvariantViolation("RETRY requires Transience.TRANSIENT")
        if self.transience is Transience.TRANSIENT and not self.evidence.has_transient_signal:
            raise InvariantViolation("TRANSIENT classification requires a transient_signal")
        if self.recommended_disposition is RecoveryDisposition.TERMINAL_CANCELLED:
            if self.reason_code is not TestReasonCode.EXECUTION_CANCELLED:
                raise InvariantViolation("TERMINAL_CANCELLED requires EXECUTION_CANCELLED reason")
            if self.transience is Transience.TRANSIENT:
                raise InvariantViolation("cancellation can never be transient")

    @property
    def is_retryable(self) -> bool:
        """True only when the disposition is a bounded retry of the same worker."""
        return self.recommended_disposition is RecoveryDisposition.RETRY

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict for graph state / audit / handoff."""
        return {
            "category": self.category.value,
            "reason_code": self.reason_code.value,
            "transience": self.transience.value,
            "recommended_disposition": self.recommended_disposition.value,
            "evidence": self.evidence.to_state_dict(),
        }
