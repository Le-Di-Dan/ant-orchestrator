"""DecisionGatePolicy — maps gate inputs to ALLOW/REQUIRE_APPROVAL/DENY (PHASE_4_PLAN C.8).

Framework-neutral domain service (no CLI, persistence or LangGraph). Energy/retry
gates reuse the Phase 3 ``EnforcementPolicy`` verbatim — no energy logic is rewritten.
Every outcome is deterministic for the same input and carries a stable reason code;
DENY never returns a free-form string.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.application.ports.energy import (
    EnergyActionPlan,
    EnergyBudget,
    EnergyDecision,
)
from ant_orchestrator.application.ports.worker import WorkerActionIntent
from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.energy.enforcement import EnforcementDecision, EnforcementPolicy
from ant_orchestrator.energy.reservation import ConsumptionOutcome
from ant_orchestrator.workflows.intent import continuation_for_gate


class DecisionGateOutcome(Enum):
    """The three possible gate outcomes (PHASE_4_PLAN C.8)."""

    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


class DecisionGateReason(Enum):
    """Stable reason codes for a gate decision (no free-form strings)."""

    NO_SIGNIFICANT_WRITE = "no_significant_write"
    SIGNIFICANT_WRITE_REQUIRES_APPROVAL = "significant_write_requires_approval"
    NO_UNSAFE_COMMAND = "no_unsafe_command"
    UNSAFE_COMMAND_REQUIRES_APPROVAL = "unsafe_command_requires_approval"
    ENERGY_WITHIN_BUDGET = "energy_within_budget"
    ENERGY_REQUIRES_APPROVAL = "energy_requires_approval"
    ENERGY_SECURITY_REJECTED = "energy_security_rejected"
    ENERGY_UNCLASSIFIED = "energy_unclassified"
    RETRY_WITHIN_LIMIT = "retry_within_limit"
    RETRY_LIMIT_REQUIRES_APPROVAL = "retry_limit_requires_approval"
    SCOPE_CHANGE_REQUIRES_APPROVAL = "scope_change_requires_approval"


@dataclass(frozen=True, slots=True)
class DecisionGateResult:
    """A deterministic gate decision with a stable reason and optional continuation."""

    outcome: DecisionGateOutcome
    reason: DecisionGateReason
    gate_type: GateType
    approved_continuation: ApprovalContinuation | None = None


def _approval(gate_type: GateType, reason: DecisionGateReason) -> DecisionGateResult:
    return DecisionGateResult(
        outcome=DecisionGateOutcome.REQUIRE_APPROVAL,
        reason=reason,
        gate_type=gate_type,
        approved_continuation=continuation_for_gate(gate_type),
    )


class DecisionGatePolicy:
    """Pure gate evaluation. Instantiate once; all methods are side-effect-free."""

    def __init__(self, enforcement: EnforcementPolicy) -> None:
        self._enforcement = enforcement

    def evaluate_significant_write(self, intent: WorkerActionIntent) -> DecisionGateResult:
        if intent.requires_significant_write:
            return _approval(
                GateType.SIGNIFICANT_WRITE,
                DecisionGateReason.SIGNIFICANT_WRITE_REQUIRES_APPROVAL,
            )
        return DecisionGateResult(
            outcome=DecisionGateOutcome.ALLOW,
            reason=DecisionGateReason.NO_SIGNIFICANT_WRITE,
            gate_type=GateType.SIGNIFICANT_WRITE,
        )

    def evaluate_unsafe_command(self, intent: WorkerActionIntent) -> DecisionGateResult:
        if intent.requires_unsafe_command:
            return _approval(
                GateType.UNSAFE_COMMAND,
                DecisionGateReason.UNSAFE_COMMAND_REQUIRES_APPROVAL,
            )
        return DecisionGateResult(
            outcome=DecisionGateOutcome.ALLOW,
            reason=DecisionGateReason.NO_UNSAFE_COMMAND,
            gate_type=GateType.UNSAFE_COMMAND,
        )

    def evaluate_energy_budget(
        self, plan: EnergyActionPlan, budget: EnergyBudget
    ) -> DecisionGateResult:
        return self._map_energy(self._enforcement.check_budget_coverage(plan, budget))

    def evaluate_energy_consumption(
        self, plan: EnergyActionPlan, outcome: ConsumptionOutcome
    ) -> DecisionGateResult:
        return self._map_energy(self._enforcement.check_consumption(plan, outcome))

    def evaluate_retry_limit(self, plan: EnergyActionPlan) -> DecisionGateResult:
        decision = self._enforcement.check_retry_limit(plan)
        if decision.decision is EnergyDecision.STOP:
            return _approval(GateType.RETRY_LIMIT, DecisionGateReason.RETRY_LIMIT_REQUIRES_APPROVAL)
        return DecisionGateResult(
            outcome=DecisionGateOutcome.ALLOW,
            reason=DecisionGateReason.RETRY_WITHIN_LIMIT,
            gate_type=GateType.RETRY_LIMIT,
        )

    def evaluate_scope_change(self) -> DecisionGateResult:
        return _approval(GateType.SCOPE_CHANGE, DecisionGateReason.SCOPE_CHANGE_REQUIRES_APPROVAL)

    def _map_energy(self, decision: EnforcementDecision) -> DecisionGateResult:
        kind = decision.decision
        if kind is EnergyDecision.ALLOW:
            return DecisionGateResult(
                outcome=DecisionGateOutcome.ALLOW,
                reason=DecisionGateReason.ENERGY_WITHIN_BUDGET,
                gate_type=GateType.ENERGY_BUDGET,
            )
        if kind in (EnergyDecision.PENDING_APPROVAL, EnergyDecision.STOP):
            return _approval(GateType.ENERGY_BUDGET, DecisionGateReason.ENERGY_REQUIRES_APPROVAL)
        if kind is EnergyDecision.REJECT:
            return DecisionGateResult(
                outcome=DecisionGateOutcome.DENY,
                reason=DecisionGateReason.ENERGY_SECURITY_REJECTED,
                gate_type=GateType.ENERGY_BUDGET,
            )
        return DecisionGateResult(
            outcome=DecisionGateOutcome.DENY,
            reason=DecisionGateReason.ENERGY_UNCLASSIFIED,
            gate_type=GateType.ENERGY_BUDGET,
        )
