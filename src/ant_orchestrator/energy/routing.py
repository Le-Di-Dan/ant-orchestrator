"""Energy routing policy — pure route selection with budget feasibility (CP8).

Evaluates action plans against current available budget snapshots and returns
typed routing decisions. No ledger mutation, no audit, no model/tool calls.

Priority order: deterministic → cache → local → cloud → rejection.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from ant_orchestrator.application.ports.energy import (
    CapabilityKind,
    EnergyActionPlan,
    EnergyBudget,
    EnergyDecision,
    QualityRequirement,
    ResourceKind,
    RoutingReason,
)

_MODEL_SATISFIES: frozenset[CapabilityKind] = frozenset(
    {CapabilityKind.LLM_INFERENCE, CapabilityKind.CODE_EXECUTION, CapabilityKind.FILE_OPERATION}
)


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    """Typed routing outcome with optional downgrade resource estimate."""

    decision: EnergyDecision
    reason: RoutingReason
    downgrade_resources: MappingProxyType[ResourceKind, int] | None = None


class RoutingPolicy:
    """Pure routing evaluator. No state; instantiate once."""

    def route(
        self,
        plan: EnergyActionPlan,
        budget: EnergyBudget,
        available: dict[ResourceKind, int | None],
    ) -> RoutingDecision:
        """Select the best eligible route.

        ``available`` maps each relevant ResourceKind to its current available
        space (``None`` means the resource has no budget limit = ungoverned).
        """
        cap = plan.required_capability

        # 1. Deterministic tool — only for DETERMINISTIC capability
        if plan.deterministic_available and cap is CapabilityKind.DETERMINISTIC:
            return RoutingDecision(
                EnergyDecision.USE_DETERMINISTIC_TOOL, RoutingReason.DETERMINISTIC_AVAILABLE
            )

        # 2. Cache — valid for any capability when caller guarantees freshness
        if plan.cache_valid:
            return RoutingDecision(EnergyDecision.USE_CACHE, RoutingReason.CACHE_HIT)

        # 3. Capability gate for model routes
        if cap not in _MODEL_SATISFIES:
            return RoutingDecision(EnergyDecision.REJECT, RoutingReason.CAPABILITY_REQUIREMENT)

        # 4. Quality gate — cloud-only quality skips local
        if plan.quality_requirement is QualityRequirement.CLOUD_REQUIRED:
            return self._cloud_or_reject(plan, RoutingReason.QUALITY_REQUIREMENT)

        # 5. Local route
        if plan.local_available:
            local = self._check_local_budget(plan, available)
            if local.decision is EnergyDecision.ROUTE_LOCAL:
                return local
            if local.decision is EnergyDecision.DOWNGRADE:
                return local
            # Budget insufficient → escalate to cloud or return budget reason
            if plan.cloud_available:
                return RoutingDecision(
                    EnergyDecision.PENDING_APPROVAL, RoutingReason.CLOUD_REQUIRES_APPROVAL
                )
            return RoutingDecision(EnergyDecision.PENDING_APPROVAL, local.reason)

        # 6. Cloud route (local structurally unavailable)
        return self._cloud_or_reject(plan, RoutingReason.LOCAL_UNAVAILABLE)

    def _check_local_budget(
        self,
        plan: EnergyActionPlan,
        available: dict[ResourceKind, int | None],
    ) -> RoutingDecision:
        for kind in plan.required_resources:
            avail = available.get(kind)
            if avail is None:
                if plan.downgrade_resources is not None:
                    return RoutingDecision(
                        EnergyDecision.DOWNGRADE,
                        RoutingReason.DOWNGRADE_AVAILABLE,
                        plan.downgrade_resources,
                    )
                return RoutingDecision(
                    EnergyDecision.PENDING_APPROVAL, RoutingReason.MISSING_REQUIRED_BUDGET
                )
            estimated = plan.estimated_resources.get(kind, 0)
            if estimated > avail:
                if plan.downgrade_resources is not None:
                    return RoutingDecision(
                        EnergyDecision.DOWNGRADE,
                        RoutingReason.DOWNGRADE_AVAILABLE,
                        plan.downgrade_resources,
                    )
                return RoutingDecision(
                    EnergyDecision.PENDING_APPROVAL, RoutingReason.BUDGET_INSUFFICIENT
                )
        return RoutingDecision(EnergyDecision.ROUTE_LOCAL, RoutingReason.LOCAL_CAPABLE)

    def _cloud_or_reject(self, plan: EnergyActionPlan, reason: RoutingReason) -> RoutingDecision:
        if plan.cloud_available:
            return RoutingDecision(
                EnergyDecision.PENDING_APPROVAL, RoutingReason.CLOUD_REQUIRES_APPROVAL
            )
        return RoutingDecision(EnergyDecision.REJECT, reason)
