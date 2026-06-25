"""Energy port — typed contracts for measurement, budget and reservation (CP7).

Defines resource kinds, budget DTO, reservation status, and error taxonomy.
Callers depend on this port without importing concrete ``energy/`` implementation.
CP8 will add EnergyManager Protocol, routing/enforcement enums, ApprovalRequest.
"""

from __future__ import annotations

from enum import Enum
from types import MappingProxyType
from typing import Final

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.errors import AntError

_RESOURCE_UNITS: Final = {
    "tokens": "integer token count",
    "api_calls": "integer call count",
    "wall_time_ms": "integer milliseconds",
    "retries": "integer retry count",
    "human_approvals": "integer approval count",
}


class ResourceKind(Enum):
    """A measurable resource governed by energy policy."""

    TOKENS = "tokens"
    API_CALLS = "api_calls"
    WALL_TIME = "wall_time_ms"
    RETRIES = "retries"
    HUMAN_APPROVALS = "human_approvals"


class MeasurementStatus(Enum):
    """Whether a measurement is estimated or actually observed."""

    ESTIMATED = "estimated"
    MEASURED = "measured"


class ReservationStatus(Enum):
    """Lifecycle state of an energy reservation."""

    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"


class EnergyBudget:
    """Immutable resource limits. Missing resource kind = not governed."""

    __slots__ = ("_limits",)

    def __init__(self, limits: dict[ResourceKind, int]) -> None:
        for kind, value in limits.items():
            if value < 0:
                raise InvariantViolation(f"EnergyBudget limit for {kind.value} must be >= 0")
        self._limits: MappingProxyType[ResourceKind, int] = MappingProxyType(dict(limits))

    @property
    def limits(self) -> MappingProxyType[ResourceKind, int]:
        return self._limits

    def limit_for(self, kind: ResourceKind) -> int | None:
        return self._limits.get(kind)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EnergyBudget):
            return NotImplemented
        return dict(self._limits) == dict(other._limits)

    def __repr__(self) -> str:
        return f"EnergyBudget(limits={dict(self._limits)})"


class EnergyError(AntError):
    """Base class for energy-related errors."""


class EnergyBudgetExceededError(EnergyError):
    """A reservation cannot be fulfilled within the remaining budget."""


class EnergyReservationError(EnergyError):
    """An invalid operation on a reservation (wrong state, not found, etc.)."""
