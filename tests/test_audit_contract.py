"""CP0 audit contract tests: AuditEvent invariants and AuditSink protocol."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.audit import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
    PolicyDecision,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from tests.support.fake_audit_sink import FakeAuditSink

TS = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))


def _event(
    detail: dict[str, str] | None = None,
    *,
    decision: PolicyDecision | None = None,
) -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.PATH_DECISION,
        correlation_id=CorrelationId("corr-1"),
        created_at=TS,
        detail=detail if detail is not None else {"path": "src/x.py"},
        decision=decision,
    )


def test_valid_event_defaults_schema_and_decision() -> None:
    event = _event()
    assert event.schema_version == AUDIT_SCHEMA_VERSION
    assert event.decision is None


def test_invalid_schema_version_rejected() -> None:
    with pytest.raises(InvariantViolation):
        AuditEvent(
            event_type=AuditEventType.EXECUTION,
            correlation_id=CorrelationId("c"),
            created_at=TS,
            detail={},
            schema_version=999,
        )


def test_correlation_id_must_be_non_empty() -> None:
    with pytest.raises(InvariantViolation):
        CorrelationId("")


def test_detail_must_be_str_to_str() -> None:
    bad: dict[str, object] = {"count": 123}
    with pytest.raises(InvariantViolation):
        AuditEvent(
            event_type=AuditEventType.EXECUTION,
            correlation_id=CorrelationId("c"),
            created_at=TS,
            detail=bad,  # type: ignore[arg-type]
        )


def test_enums_serialize_by_stable_value() -> None:
    assert PolicyDecision.DENY.value == "deny"
    assert PolicyDecision.ALLOW.value == "allow"
    assert AuditEventType.CONTEXT_BUILD.value == "context_build"
    assert AuditEventType.ENERGY_ENFORCEMENT.value == "energy_enforcement"


def test_fake_sink_satisfies_protocol_and_records_in_order() -> None:
    sink = FakeAuditSink()
    assert isinstance(sink, AuditSink)
    first = _event(decision=PolicyDecision.ALLOW)
    second = _event(decision=PolicyDecision.DENY)
    sink.write(first)
    sink.write(second)
    assert sink.events == [first, second]
