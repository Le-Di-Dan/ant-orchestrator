"""Single-process worker energy lifecycle (PHASE_5_PLAN CP5).

A deterministic, in-memory implementation of ``WorkerEnergyLifecycle``. It maps a
reservation reference to its reserved token amount, reverifies validity before a
provider call, and settles consumption afterwards — charging measured usage when
present and a conservative fallback (the reserved amount, never zero) when usage is
``UNAVAILABLE``. Settlement is idempotent per ``invocation_id`` so a recovery replay
never double-charges. Durable, DB-backed reconciliation is wired only in CP6; here the
durability of "already settled" is carried by the caller's composition receipt.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.llm import ModelUsage, UsageStatus
from ant_orchestrator.application.ports.worker_energy import (
    EnergyReverifyOutcome,
    EnergyReverifyResult,
    EnergySettlement,
    SettlementOutcome,
)
from ant_orchestrator.core.domain.errors import InvariantViolation


@dataclass
class _ReservationState:
    reserved_tokens: int
    valid: bool


class InMemoryEnergyLifecycle:
    """In-process reverify/settle ledger keyed by reservation reference."""

    def __init__(self) -> None:
        self._reservations: dict[str, _ReservationState] = {}
        self._settled: dict[str, EnergySettlement] = {}

    # --- seeding (composition root / tests; CP6 replaces with a real ledger) ---
    def reserve(self, reservation_ref: str, reserved_tokens: int) -> None:
        """Register a reservation reference with its reserved token amount."""
        if not reservation_ref:
            raise InvariantViolation("reservation_ref must be non-empty")
        if reserved_tokens < 0:
            raise InvariantViolation("reserved_tokens must be >= 0")
        self._reservations[reservation_ref] = _ReservationState(reserved_tokens, valid=True)

    def invalidate(self, reservation_ref: str) -> None:
        """Mark a reservation no longer valid (e.g. expired or revoked)."""
        state = self._reservations.get(reservation_ref)
        if state is not None:
            state.valid = False

    # --- lifecycle ---------------------------------------------------------
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
            return existing  # idempotent: never settle the same invocation twice
        state = self._reservations.get(reservation_ref)
        reserved = state.reserved_tokens if state is not None else 0
        actual, fallback = self._consumption(usage, reserved)
        over_budget = actual > reserved
        outcome = SettlementOutcome.OVER_BUDGET if over_budget else SettlementOutcome.SETTLED
        reason = "conservative fallback" if fallback else "measured usage settled"
        settlement = EnergySettlement(
            outcome=outcome,
            actual_tokens=actual,
            fallback_used=fallback,
            reason="over budget" if over_budget else reason,
            settlement_ref=invocation_id,
        )
        self._settled[invocation_id] = settlement
        return settlement

    @staticmethod
    def _consumption(usage: ModelUsage, reserved: int) -> tuple[int, bool]:
        if usage.status is UsageStatus.UNAVAILABLE:
            # Conservative: charge the reserved amount, never zero (honest accounting).
            return reserved, True
        if usage.tokens_total is not None:
            return usage.tokens_total.value, False
        tin = usage.tokens_in.value if usage.tokens_in is not None else 0
        tout = usage.tokens_out.value if usage.tokens_out is not None else 0
        return tin + tout, False
