"""Energy measurement — typed resource consumption records (CP7).

Immutable records tracking estimated or actual resource usage. No provider
SDK, no network, no prompt/output storage. Multiple resource kinds in a
single snapshot via ``ResourceAmount``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.energy import (
    MeasurementStatus,
    ResourceKind,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import UtcTimestamp


@dataclass(frozen=True, slots=True)
class ResourceAmount:
    """A single resource measurement: kind + non-negative integer amount."""

    kind: ResourceKind
    amount: int

    def __post_init__(self) -> None:
        if self.amount < 0:
            raise InvariantViolation("ResourceAmount.amount must be >= 0")


@dataclass(frozen=True, slots=True)
class EnergyMeasurement:
    """An immutable snapshot of resource consumption."""

    amounts: tuple[ResourceAmount, ...]
    status: MeasurementStatus
    recorded_at: UtcTimestamp
    correlation_id: str | None = None

    def __post_init__(self) -> None:
        kinds = [a.kind for a in self.amounts]
        if len(kinds) != len(set(kinds)):
            raise InvariantViolation("EnergyMeasurement must not have duplicate resource kinds")

    def amount_for(self, kind: ResourceKind) -> int:
        for a in self.amounts:
            if a.kind is kind:
                return a.amount
        return 0
