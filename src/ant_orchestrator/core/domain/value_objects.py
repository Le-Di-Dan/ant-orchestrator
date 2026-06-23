"""Immutable domain value objects (PHASE_1_PLAN §7.1).

Identifiers are distinct types wrapping a non-empty string so that, e.g., a
``TaskId`` cannot be passed where a ``WorkerRunId`` is expected. Timestamps are
always timezone-aware UTC; token counts are non-negative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from ant_orchestrator.core.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class Identifier:
    """Base class for opaque string identifiers."""

    value: str

    def __post_init__(self) -> None:
        if not self.value:
            raise InvariantViolation(f"{type(self).__name__} must be a non-empty string")

    def __str__(self) -> str:
        return self.value


class TaskId(Identifier):
    """Identity of a Task."""


class WorkerRunId(Identifier):
    """Identity of a WorkerRun."""


class EnergyUsageId(Identifier):
    """Identity of an EnergyUsage record."""


class CheckpointId(Identifier):
    """Identity of a WorkflowCheckpoint."""


class ApprovalId(Identifier):
    """Identity of an Approval."""


class EvidenceId(Identifier):
    """Identity of an ExecutionEvidence record."""


class HandoffId(Identifier):
    """Identity of a HandoffRecord."""


class PheromoneId(Identifier):
    """Identity of a PheromoneRecord."""


class MemoryId(Identifier):
    """Identity of a MemoryRecord."""


@dataclass(frozen=True, slots=True)
class UtcTimestamp:
    """A timezone-aware timestamp pinned to UTC, serialized as ISO-8601."""

    value: datetime

    def __post_init__(self) -> None:
        offset = self.value.utcoffset()
        if offset is None or offset != timedelta(0):
            raise InvariantViolation("UtcTimestamp must be timezone-aware and in UTC")

    @classmethod
    def from_datetime(cls, value: datetime) -> UtcTimestamp:
        """Build from any aware datetime, normalizing to UTC."""
        if value.tzinfo is None:
            raise InvariantViolation("Cannot build UtcTimestamp from a naive datetime")
        return cls(value.astimezone(UTC))

    @classmethod
    def from_iso(cls, text: str) -> UtcTimestamp:
        """Parse an ISO-8601 string into a UTC timestamp."""
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise InvariantViolation(f"Invalid ISO-8601 timestamp: {text!r}") from exc
        return cls.from_datetime(parsed)

    def to_iso(self) -> str:
        """Render as an ISO-8601 string in UTC."""
        return self.value.isoformat()


@dataclass(frozen=True, slots=True)
class TokenCount:
    """A non-negative token count."""

    value: int

    def __post_init__(self) -> None:
        if self.value < 0:
            raise InvariantViolation("TokenCount must be >= 0")
