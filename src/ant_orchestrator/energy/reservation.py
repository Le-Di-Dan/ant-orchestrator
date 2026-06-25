"""Energy reservation ledger — single-process budget tracking (CP7).

The ledger tracks committed budget space (reserved + consumed) per resource
kind. Reservations are atomic: a multi-resource request either fully reserves
or fully fails with no partial mutation. No distributed locking, no background
threads, no database — pure in-memory for MVP.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ant_orchestrator.application.ports.energy import (
    EnergyBudget,
    EnergyBudgetExceededError,
    EnergyReservationError,
    ReservationStatus,
    ResourceKind,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator


@dataclass(frozen=True, slots=True)
class EnergyReservation:
    """Immutable snapshot of a reservation at a point in time."""

    id: str
    amounts: MappingProxyType[ResourceKind, int]
    status: ReservationStatus
    created_at: UtcTimestamp
    consumed_amounts: MappingProxyType[ResourceKind, int] | None = None

    def __post_init__(self) -> None:
        for v in self.amounts.values():
            if v < 0:
                raise InvariantViolation("Reservation amount must be >= 0")
        if self.consumed_amounts is not None:
            for v in self.consumed_amounts.values():
                if v < 0:
                    raise InvariantViolation("Consumed amount must be >= 0")


@dataclass(frozen=True, slots=True)
class ConsumptionOutcome:
    """Result of consuming a reservation with actual resource usage."""

    reservation_id: str
    overrun: bool
    excess: MappingProxyType[ResourceKind, int]


class ReservationLedger:
    """Single-process in-memory reservation ledger.

    Tracks committed budget per resource kind. ``committed[kind]`` equals the sum
    of all active RESERVED amounts plus all CONSUMED actual amounts. Available
    space for new reservations = ``budget.limit - committed``.
    """

    def __init__(
        self,
        budget: EnergyBudget,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._budget = budget
        self._clock = clock
        self._ids = id_gen
        self._committed: dict[ResourceKind, int] = {k: 0 for k in budget.limits}
        self._reservations: dict[str, EnergyReservation] = {}

    def reserve(self, amounts: dict[ResourceKind, int]) -> EnergyReservation:
        if not amounts:
            raise InvariantViolation("Reservation must request at least one resource")
        for kind, amount in amounts.items():
            if amount < 0:
                raise InvariantViolation("Reservation amount must be >= 0")
            limit = self._budget.limit_for(kind)
            if limit is None:
                continue
            available = limit - self._committed.get(kind, 0)
            if amount > available:
                raise EnergyBudgetExceededError(
                    f"{kind.value}: requested {amount}, available {available}"
                )
        rid = self._ids.new_id()
        if rid in self._reservations:
            raise InvariantViolation("Duplicate reservation ID")
        for kind, amount in amounts.items():
            if kind in self._committed:
                self._committed[kind] += amount
        now = self._clock.now()
        reservation = EnergyReservation(
            id=rid,
            amounts=MappingProxyType(dict(amounts)),
            status=ReservationStatus.RESERVED,
            created_at=now,
        )
        self._reservations[rid] = reservation
        return reservation

    def consume(
        self,
        reservation_id: str,
        actual: dict[ResourceKind, int],
    ) -> ConsumptionOutcome:
        res = self._get_active(reservation_id, ReservationStatus.RESERVED)
        excess: dict[ResourceKind, int] = {}
        has_overrun = False
        for kind in set(res.amounts) | set(actual):
            reserved_amt = res.amounts.get(kind, 0)
            actual_amt = actual.get(kind, 0)
            if actual_amt < 0:
                raise InvariantViolation("Actual amount must be >= 0")
            delta = actual_amt - reserved_amt
            if kind in self._committed:
                self._committed[kind] += delta
            over = max(0, delta)
            excess[kind] = over
            if over > 0:
                has_overrun = True
        consumed = EnergyReservation(
            id=res.id,
            amounts=res.amounts,
            status=ReservationStatus.CONSUMED,
            created_at=res.created_at,
            consumed_amounts=MappingProxyType(dict(actual)),
        )
        self._reservations[reservation_id] = consumed
        return ConsumptionOutcome(
            reservation_id=reservation_id,
            overrun=has_overrun,
            excess=MappingProxyType(excess),
        )

    def release(self, reservation_id: str) -> EnergyReservation:
        res = self._get_active(reservation_id, ReservationStatus.RESERVED)
        for kind, amount in res.amounts.items():
            if kind in self._committed:
                self._committed[kind] = max(0, self._committed[kind] - amount)
        released = EnergyReservation(
            id=res.id,
            amounts=res.amounts,
            status=ReservationStatus.RELEASED,
            created_at=res.created_at,
        )
        self._reservations[reservation_id] = released
        return released

    def get(self, reservation_id: str) -> EnergyReservation:
        if reservation_id not in self._reservations:
            raise EnergyReservationError(f"Reservation {reservation_id} not found")
        return self._reservations[reservation_id]

    def available(self, kind: ResourceKind) -> int | None:
        limit = self._budget.limit_for(kind)
        if limit is None:
            return None
        return max(0, limit - self._committed.get(kind, 0))

    def _get_active(
        self,
        reservation_id: str,
        expected: ReservationStatus,
    ) -> EnergyReservation:
        if reservation_id not in self._reservations:
            raise EnergyReservationError(f"Reservation {reservation_id} not found")
        res = self._reservations[reservation_id]
        if res.status is not expected:
            raise EnergyReservationError(
                f"Reservation {reservation_id} is {res.status.value}, expected {expected.value}"
            )
        return res
