"""Canonical category → classification policy for the Test Ant (PHASE_6_PLAN §F).

Pure domain policy: maps every :class:`FailureCategory` to its default transience,
recommended disposition and reason code. There is exactly one rule per category, so the
mapping is exhaustive — adding a category without a rule makes
:func:`default_classification` raise (and the CP1 test suite fails).

This module holds NO I/O and NO classifier logic. The CP3 classifier observes process
facts, picks a category, then uses this policy to build the canonical classification.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    FailureClassification,
    FailureEvidence,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
    TransientSignal,
)


@dataclass(frozen=True, slots=True)
class CategoryRule:
    """The default classification facets for one :class:`FailureCategory`."""

    transience: Transience
    disposition: RecoveryDisposition
    reason_code: TestReasonCode
    transient_signal: TransientSignal | None = None


_T = Transience
_D = RecoveryDisposition
_R = TestReasonCode

# Exhaustive: one rule per FailureCategory. Plain ``TEST_DEADLINE_EXCEEDED`` is UNKNOWN +
# ESCALATE (never a default retry). Only the two transient categories carry a signal and
# may map to RETRY.
_CATEGORY_POLICY: MappingProxyType[FailureCategory, CategoryRule] = MappingProxyType(
    {
        FailureCategory.TRANSIENT_INTERRUPTION: CategoryRule(
            _T.TRANSIENT,
            _D.RETRY,
            _R.TRANSIENT_INTERRUPTION_AUDITED,
            TransientSignal.PROCESS_INTERRUPTION,
        ),
        FailureCategory.ADAPTER_TRANSIENT: CategoryRule(
            _T.TRANSIENT,
            _D.RETRY,
            _R.ADAPTER_TEMPORARILY_UNAVAILABLE,
            TransientSignal.ADAPTER_RESOURCE_UNAVAILABLE,
        ),
        FailureCategory.TEST_DEADLINE_EXCEEDED: CategoryRule(
            _T.UNKNOWN, _D.ESCALATE, _R.TEST_DEADLINE_EXCEEDED
        ),
        FailureCategory.EXECUTABLE_MISSING: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.EXECUTABLE_MISSING
        ),
        FailureCategory.PERMISSION_DENIED: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.PERMISSION_DENIED
        ),
        FailureCategory.ADAPTER_CONFIG_INVALID: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.INVALID_ADAPTER_CONFIGURATION
        ),
        FailureCategory.DETERMINISTIC_TEST_FAILURE: CategoryRule(
            _T.DETERMINISTIC, _D.ESCALATE, _R.DETERMINISTIC_TEST_FAILURE
        ),
        FailureCategory.POLICY_VIOLATION: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.COMMAND_POLICY_DENIED
        ),
        FailureCategory.INVALID_COMMAND: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.INVALID_COMMAND
        ),
        FailureCategory.EXECUTION_BOUNDARY_FAILURE: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.EXECUTION_BOUNDARY_DENIED
        ),
        FailureCategory.ISOLATION_VIOLATION: CategoryRule(
            _T.DETERMINISTIC, _D.TERMINAL_FAILED, _R.ISOLATION_VIOLATION
        ),
        FailureCategory.EXECUTION_ISOLATION_UNAVAILABLE: CategoryRule(
            _T.DETERMINISTIC, _D.ESCALATE, _R.EXECUTION_ISOLATION_UNAVAILABLE
        ),
        FailureCategory.ISOLATION_SETUP_FAILURE: CategoryRule(
            _T.DETERMINISTIC, _D.ESCALATE, _R.ISOLATION_SETUP_FAILED
        ),
        FailureCategory.BUDGET_EXHAUSTED: CategoryRule(
            _T.DETERMINISTIC, _D.ESCALATE, _R.BUDGET_EXHAUSTED
        ),
        FailureCategory.UNKNOWN: CategoryRule(_T.UNKNOWN, _D.ESCALATE, _R.UNKNOWN_FAILURE),
    }
)


def category_rule(category: FailureCategory) -> CategoryRule:
    """Return the canonical rule for ``category`` or raise if none is registered."""
    try:
        return _CATEGORY_POLICY[category]
    except KeyError as exc:  # pragma: no cover - guarded by the exhaustiveness test
        raise InvariantViolation(f"no classification policy for category {category.value}") from exc


def default_classification(
    category: FailureCategory,
    *,
    evidence_refs: tuple[str, ...] = (),
    detail_code: str | None = None,
) -> FailureClassification:
    """Build the canonical :class:`FailureClassification` for ``category``.

    The category's audited transient signal (if any) is attached automatically, so a
    ``TRANSIENT`` result always carries the evidence its invariant requires. Extra
    sanitized ``evidence_refs`` / ``detail_code`` from the classifier are merged in.
    """
    rule = category_rule(category)
    evidence = FailureEvidence(
        evidence_refs=evidence_refs,
        transient_signal=rule.transient_signal,
        detail_code=detail_code,
    )
    return FailureClassification(
        category=category,
        reason_code=rule.reason_code,
        transience=rule.transience,
        recommended_disposition=rule.disposition,
        evidence=evidence,
    )


def cancellation_classification(
    *, evidence_refs: tuple[str, ...] = (), detail_code: str | None = None
) -> FailureClassification:
    """Build the terminal-cancelled classification (not a category-driven failure).

    Cancellation is not a failure category: it is represented by the dedicated
    ``TERMINAL_CANCELLED`` disposition and ``EXECUTION_CANCELLED`` reason, and is never
    routed as retry or regroup.
    """
    return FailureClassification(
        category=FailureCategory.UNKNOWN,
        reason_code=TestReasonCode.EXECUTION_CANCELLED,
        transience=Transience.DETERMINISTIC,
        recommended_disposition=RecoveryDisposition.TERMINAL_CANCELLED,
        evidence=FailureEvidence(evidence_refs=evidence_refs, detail_code=detail_code),
    )
