"""Worker energy lifecycle contract — reverify + settle around a provider call (CP5).

The Documentation Ant reverifies an existing energy reservation BEFORE invoking the
provider and settles consumption AFTER. Settlement is honest about missing data:
when usage is ``UNAVAILABLE`` the implementation must fall back conservatively (never
zero). Settlement is idempotent per ``invocation_id`` so recovery never double-charges.

This port carries no provider type and no DB type; the durable, DB-backed reconciliation
is wired only in CP6. The CP5 implementation is single-process and deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.llm import ModelUsage


class EnergyReverifyOutcome(Enum):
    """Whether a reservation is still valid for a provider call."""

    VALID = "valid"
    INVALID = "invalid"
    EXPIRED = "expired"
    OVER_POLICY = "over_policy"


class SettlementOutcome(Enum):
    """The outcome of settling consumption against a reservation."""

    SETTLED = "settled"
    OVER_BUDGET = "over_budget"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EnergyReverifyResult:
    """Typed reverify outcome — sanitized reason, no raw exception."""

    outcome: EnergyReverifyOutcome
    reason: str

    @property
    def ok(self) -> bool:
        return self.outcome is EnergyReverifyOutcome.VALID


@dataclass(frozen=True, slots=True)
class EnergySettlement:
    """Typed settlement record distinguishing actual vs conservative fallback.

    ``actual_tokens`` is the settled consumption (measured OR conservative fallback).
    ``fallback_used`` is True iff usage was unavailable and the reserved amount was
    charged conservatively. ``settlement_ref`` anchors the stable invocation identity.
    """

    outcome: SettlementOutcome
    actual_tokens: int
    fallback_used: bool
    reason: str
    settlement_ref: str

    @property
    def settled(self) -> bool:
        return self.outcome in (SettlementOutcome.SETTLED, SettlementOutcome.OVER_BUDGET)


@runtime_checkable
class WorkerEnergyLifecycle(Protocol):
    """Reverify-before-call and settle-after-call energy boundary for one worker call."""

    def reverify(self, reservation_ref: str) -> EnergyReverifyResult:
        """Reverify that ``reservation_ref`` is still valid for a provider call."""
        ...

    def settle(
        self, reservation_ref: str, invocation_id: str, usage: ModelUsage
    ) -> EnergySettlement:
        """Settle consumption; idempotent per ``invocation_id`` (no double-charge)."""
        ...
