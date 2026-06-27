"""CP1 — exhaustive classification → disposition → worker-outcome mapping (§F)."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.test_execution import worker_outcome_for
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
)
from ant_orchestrator.core.domain.test_failure_policy import (
    cancellation_classification,
    default_classification,
)

# Expected (transience, disposition, worker_outcome) per category — the §F decision table.
_EXPECTED: dict[FailureCategory, tuple[Transience, RecoveryDisposition, WorkerOutcome]] = {
    FailureCategory.TRANSIENT_INTERRUPTION: (
        Transience.TRANSIENT,
        RecoveryDisposition.RETRY,
        WorkerOutcome.RETRYABLE_FAILURE,
    ),
    FailureCategory.ADAPTER_TRANSIENT: (
        Transience.TRANSIENT,
        RecoveryDisposition.RETRY,
        WorkerOutcome.RETRYABLE_FAILURE,
    ),
    FailureCategory.TEST_DEADLINE_EXCEEDED: (
        Transience.UNKNOWN,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
    FailureCategory.EXECUTABLE_MISSING: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.PERMISSION_DENIED: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.ADAPTER_CONFIG_INVALID: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.DETERMINISTIC_TEST_FAILURE: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
    FailureCategory.POLICY_VIOLATION: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.INVALID_COMMAND: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.EXECUTION_BOUNDARY_FAILURE: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.ISOLATION_VIOLATION: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.TERMINAL_FAILED,
        WorkerOutcome.PERMANENT_FAILURE,
    ),
    FailureCategory.EXECUTION_ISOLATION_UNAVAILABLE: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
    FailureCategory.ISOLATION_SETUP_FAILURE: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
    FailureCategory.BUDGET_EXHAUSTED: (
        Transience.DETERMINISTIC,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
    FailureCategory.UNKNOWN: (
        Transience.UNKNOWN,
        RecoveryDisposition.ESCALATE,
        WorkerOutcome.ESCALATION,
    ),
}


def test_every_category_has_a_policy() -> None:
    # Fails when a new FailureCategory is added without a mapping (no wildcard fallback).
    for category in FailureCategory:
        assert category in _EXPECTED, f"no expected mapping for {category.value}"
        # default_classification must not raise (policy is exhaustive too).
        default_classification(category)


@pytest.mark.parametrize("category", list(FailureCategory))
def test_category_maps_as_specified(category: FailureCategory) -> None:
    transience, disposition, outcome = _EXPECTED[category]
    clf = default_classification(category)
    assert clf.transience is transience
    assert clf.recommended_disposition is disposition
    assert worker_outcome_for(clf.recommended_disposition) is outcome


def test_only_transient_categories_retry() -> None:
    for category in FailureCategory:
        clf = default_classification(category)
        if clf.recommended_disposition is RecoveryDisposition.RETRY:
            assert clf.transience is Transience.TRANSIENT
            assert clf.evidence.has_transient_signal


def test_plain_deadline_does_not_retry() -> None:
    clf = default_classification(FailureCategory.TEST_DEADLINE_EXCEEDED)
    assert clf.recommended_disposition is not RecoveryDisposition.RETRY
    assert not clf.is_retryable


def test_executable_missing_and_permission_are_terminal() -> None:
    for category in (FailureCategory.EXECUTABLE_MISSING, FailureCategory.PERMISSION_DENIED):
        clf = default_classification(category)
        assert clf.recommended_disposition is RecoveryDisposition.TERMINAL_FAILED
        assert worker_outcome_for(clf.recommended_disposition) is WorkerOutcome.PERMANENT_FAILURE


def test_isolation_unavailable_fails_closed_without_retry() -> None:
    clf = default_classification(FailureCategory.EXECUTION_ISOLATION_UNAVAILABLE)
    assert clf.reason_code is TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE
    assert clf.recommended_disposition is RecoveryDisposition.ESCALATE
    assert not clf.is_retryable


def test_worker_outcome_is_exhaustive_over_failure_dispositions() -> None:
    for disposition in RecoveryDisposition:
        if disposition is RecoveryDisposition.TERMINAL_CANCELLED:
            continue
        assert isinstance(worker_outcome_for(disposition), WorkerOutcome)


def test_cancellation_maps_to_terminal_cancelled_not_retry() -> None:
    clf = cancellation_classification()
    assert clf.recommended_disposition is RecoveryDisposition.TERMINAL_CANCELLED
    assert clf.reason_code is TestReasonCode.EXECUTION_CANCELLED
    assert not clf.is_retryable
    # Cancellation is never routed as a worker failure outcome.
    with pytest.raises(InvariantViolation):
        worker_outcome_for(RecoveryDisposition.TERMINAL_CANCELLED)
