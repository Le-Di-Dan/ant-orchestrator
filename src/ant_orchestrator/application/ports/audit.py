"""Audit sink port and audit event contract (CP0).

The single typed boundary for emitting audit evidence. :class:`AuditEvent` is an
immutable, sanitized record: its ``detail`` carries only short string values and
must never embed raw prompts, environment dumps, secrets, private keys, tokens or
unbounded command/stdout/stderr. Business logic decides on typed enums
(``event_type``/``decision``), never by parsing ``detail``. Concrete sinks live in
the adapters layer; inner layers depend only on :class:`AuditSink`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, Protocol, runtime_checkable

from ant_orchestrator.core.domain.enums import PolicyDecision as PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import Identifier, UtcTimestamp

# Serialization schema version for persisted audit events (distinct from config,
# workspace and DB schema versions). Bump when the on-disk event shape changes.
AUDIT_SCHEMA_VERSION: Final = 1


class CorrelationId(Identifier):
    """Correlates audit events, evidence and energy/approval records for one action."""


class AuditEventType(Enum):
    """The kind of decision or observation an audit event records."""

    PATH_DECISION = "path_decision"
    COMMAND_DECISION = "command_decision"
    EXECUTION = "execution"
    OUTPUT_TRUNCATED = "output_truncated"
    CONTEXT_BUILD = "context_build"
    ENERGY_RESERVATION = "energy_reservation"
    ROUTING_DECISION = "routing_decision"
    ENERGY_ENFORCEMENT = "energy_enforcement"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, sanitized audit record describing one decision/observation."""

    event_type: AuditEventType
    correlation_id: CorrelationId
    created_at: UtcTimestamp
    detail: Mapping[str, str]
    decision: PolicyDecision | None = None
    schema_version: int = AUDIT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != AUDIT_SCHEMA_VERSION:
            raise InvariantViolation(f"AuditEvent.schema_version must be {AUDIT_SCHEMA_VERSION}")
        for key, value in self.detail.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise InvariantViolation("AuditEvent.detail must be a str->str mapping")


@runtime_checkable
class AuditSink(Protocol):
    """Emits audit events. Implementations MUST redact before persisting."""

    def write(self, event: AuditEvent) -> None:
        """Persist or forward one audit event."""
        ...
