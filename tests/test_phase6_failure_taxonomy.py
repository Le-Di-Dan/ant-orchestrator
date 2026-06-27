"""CP1 — Test Ant failure taxonomy: enum stability + classification invariants."""

from __future__ import annotations

import json

import pytest

from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvalidStatusValue, InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    FailureClassification,
    FailureEvidence,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
    TransientSignal,
)

_TAXONOMY_ENUMS = (
    FailureCategory,
    Transience,
    RecoveryDisposition,
    TransientSignal,
    TestReasonCode,
)


@pytest.mark.parametrize("enum_cls", _TAXONOMY_ENUMS)
def test_values_are_unique_strings(enum_cls: type[_StrEnum]) -> None:
    values = [m.value for m in enum_cls]
    assert all(isinstance(v, str) for v in values)
    assert len(values) == len(set(values)), f"{enum_cls.__name__} has duplicate values"


@pytest.mark.parametrize("enum_cls", _TAXONOMY_ENUMS)
def test_parse_round_trips(enum_cls: type[_StrEnum]) -> None:
    for member in enum_cls:
        assert enum_cls.parse(member.value) is member
        assert str(member) == member.value


@pytest.mark.parametrize("enum_cls", _TAXONOMY_ENUMS)
def test_parse_unknown_raises(enum_cls: type[_StrEnum]) -> None:
    with pytest.raises(InvalidStatusValue):
        enum_cls.parse("definitely_not_a_member")


def test_required_category_semantics_present() -> None:
    # A generic retryable TIMEOUT must not exist; deadline is its own category.
    assert FailureCategory.TEST_DEADLINE_EXCEEDED in set(FailureCategory)
    assert not any(m.value == "timeout" for m in FailureCategory)


def test_reason_codes_have_no_duplicates() -> None:
    values = [m.value for m in TestReasonCode]
    assert len(values) == len(set(values))


# --- FailureClassification invariants -----------------------------------------


def _transient_evidence() -> FailureEvidence:
    return FailureEvidence(transient_signal=TransientSignal.PROCESS_INTERRUPTION)


def test_retry_requires_transient() -> None:
    with pytest.raises(InvariantViolation):
        FailureClassification(
            category=FailureCategory.EXECUTABLE_MISSING,
            reason_code=TestReasonCode.EXECUTABLE_MISSING,
            transience=Transience.DETERMINISTIC,
            recommended_disposition=RecoveryDisposition.RETRY,
        )


def test_unknown_cannot_retry() -> None:
    with pytest.raises(InvariantViolation):
        FailureClassification(
            category=FailureCategory.UNKNOWN,
            reason_code=TestReasonCode.UNKNOWN_FAILURE,
            transience=Transience.UNKNOWN,
            recommended_disposition=RecoveryDisposition.RETRY,
        )


def test_transient_requires_signal() -> None:
    with pytest.raises(InvariantViolation):
        FailureClassification(
            category=FailureCategory.TRANSIENT_INTERRUPTION,
            reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
            transience=Transience.TRANSIENT,
            recommended_disposition=RecoveryDisposition.RETRY,
            evidence=FailureEvidence(),  # no signal
        )


def test_valid_transient_retry_is_accepted() -> None:
    clf = FailureClassification(
        category=FailureCategory.TRANSIENT_INTERRUPTION,
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        transience=Transience.TRANSIENT,
        recommended_disposition=RecoveryDisposition.RETRY,
        evidence=_transient_evidence(),
    )
    assert clf.is_retryable


def test_terminal_cancelled_requires_cancelled_reason() -> None:
    with pytest.raises(InvariantViolation):
        FailureClassification(
            category=FailureCategory.UNKNOWN,
            reason_code=TestReasonCode.UNKNOWN_FAILURE,
            transience=Transience.DETERMINISTIC,
            recommended_disposition=RecoveryDisposition.TERMINAL_CANCELLED,
        )


def test_evidence_rejects_raw_multiline_output() -> None:
    with pytest.raises(InvariantViolation):
        FailureEvidence(detail_code="traceback line 1\nline 2")


def test_evidence_rejects_overflowing_refs() -> None:
    with pytest.raises(InvariantViolation):
        FailureEvidence(evidence_refs=tuple(f"ref-{i}" for i in range(17)))


def test_classification_is_json_safe() -> None:
    clf = FailureClassification(
        category=FailureCategory.ADAPTER_TRANSIENT,
        reason_code=TestReasonCode.ADAPTER_TEMPORARILY_UNAVAILABLE,
        transience=Transience.TRANSIENT,
        recommended_disposition=RecoveryDisposition.RETRY,
        evidence=FailureEvidence(
            evidence_refs=("audit:42",),
            transient_signal=TransientSignal.ADAPTER_RESOURCE_UNAVAILABLE,
            detail_code="resource_busy",
        ),
    )
    payload = clf.to_state_dict()
    # Round-trips through JSON without loss and contains no raw objects.
    assert json.loads(json.dumps(payload)) == payload
    assert payload["reason_code"] == "adapter_temporarily_unavailable"
