"""Production worker energy lifecycle paired with durable settlement (PHASE_5_PLAN CP6).

CP6 forbids the in-memory CP5 lifecycle as the production durable authority. This class
is the production ``WorkerEnergyLifecycle``: it reverifies the reservation seeded from the
approved scope before the provider call and settles consumption afterwards, idempotent per
``invocation_id``. The DURABLE record of that settlement is a row in the ``energy_usage``
table, written by the persistence mapper inside the same unit of work as WorkerRun and
ExecutionEvidence — this object only computes the honest in-phase decision (recorded into
the durable composition receipt). It is deliberately NOT an ``InMemoryEnergyLifecycle`` so
the production composition root provably injects a durable-paired authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.llm import ModelUsage
from ant_orchestrator.application.ports.worker_energy import (
    EnergyReverifyOutcome,
    EnergyReverifyResult,
    EnergySettlement,
    SettlementOutcome,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.energy.settlement_math import compute_consumption


@dataclass
class _Reservation:
    reserved_tokens: int
    valid: bool = True


class DurableEnergyLifecycle:
    """Reverify/settle bound to the approved reservation; durable via the energy row."""

    def __init__(self) -> None:
        self._reservations: dict[str, _Reservation] = {}
        self._settled: dict[str, EnergySettlement] = {}

    def reserve(self, reservation_ref: str, reserved_tokens: int) -> None:
        """Seed the reservation authority from the approved proposal/scope estimate."""
        if not reservation_ref:
            raise InvariantViolation("reservation_ref must be non-empty")
        if reserved_tokens < 0:
            raise InvariantViolation("reserved_tokens must be >= 0")
        self._reservations[reservation_ref] = _Reservation(reserved_tokens)

    def invalidate(self, reservation_ref: str) -> None:
        """Mark a reservation no longer valid (expired/revoked)."""
        state = self._reservations.get(reservation_ref)
        if state is not None:
            state.valid = False

    def reverify(self, reservation_ref: str) -> EnergyReverifyResult:
        state = self._reservations.get(reservation_ref)
        if state is None:
            return EnergyReverifyResult(EnergyReverifyOutcome.INVALID, "reservation not found")
        if not state.valid:
            return EnergyReverifyResult(
                EnergyReverifyOutcome.EXPIRED, "reservation no longer valid"
            )
        return EnergyReverifyResult(EnergyReverifyOutcome.VALID, "reservation valid")

    def settle(
        self, reservation_ref: str, invocation_id: str, usage: ModelUsage
    ) -> EnergySettlement:
        if not invocation_id:
            raise InvariantViolation("invocation_id must be non-empty")
        existing = self._settled.get(invocation_id)
        if existing is not None:
            return existing  # idempotent per invocation: never double-charge
        state = self._reservations.get(reservation_ref)
        reserved = state.reserved_tokens if state is not None else 0
        actual, fallback = compute_consumption(usage, reserved)
        over_budget = actual > reserved
        settlement = EnergySettlement(
            outcome=SettlementOutcome.OVER_BUDGET if over_budget else SettlementOutcome.SETTLED,
            actual_tokens=actual,
            fallback_used=fallback,
            reason="over budget"
            if over_budget
            else ("conservative fallback" if fallback else "measured usage settled"),
            settlement_ref=invocation_id,
        )
        self._settled[invocation_id] = settlement
        return settlement
