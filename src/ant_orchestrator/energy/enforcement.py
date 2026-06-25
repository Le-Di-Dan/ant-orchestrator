"""Energy enforcement policy — pure budget coverage and overrun decisions (CP8).

Stateless checks against plans, budgets, and consumption outcomes. No ledger
mutation, no audit calls, no side effects, no provider SDK.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.energy import (
    ApprovalReason,
    BudgetCoverage,
    ContextDisposition,
    EnergyActionPlan,
    EnergyBudget,
    EnergyDecision,
    EnforcementReason,
)
from ant_orchestrator.energy.reservation import ConsumptionOutcome


@dataclass(frozen=True, slots=True)
class EnforcementDecision:
    """Typed result of an enforcement policy check."""

    decision: EnergyDecision
    reason: EnforcementReason
    approval_reason: ApprovalReason | None = None
    coverage: BudgetCoverage | None = None


class EnforcementPolicy:
    """Pure enforcement checks. Instantiate once; all methods are side-effect-free."""

    def check_budget_coverage(
        self,
        plan: EnergyActionPlan,
        budget: EnergyBudget,
    ) -> EnforcementDecision:
        """Verify every required resource has a governed limit.

        A missing limit for a required resource is MISSING_REQUIRED_LIMIT,
        not an implicit allow.
        """
        for kind in plan.required_resources:
            if budget.limit_for(kind) is None:
                return EnforcementDecision(
                    decision=EnergyDecision.PENDING_APPROVAL,
                    reason=EnforcementReason.MISSING_REQUIRED_BUDGET,
                    approval_reason=ApprovalReason.BUDGET_INSUFFICIENT,
                    coverage=BudgetCoverage.MISSING_REQUIRED_LIMIT,
                )
        return EnforcementDecision(
            decision=EnergyDecision.ALLOW,
            reason=EnforcementReason.WITHIN_BUDGET,
            coverage=BudgetCoverage.GOVERNED,
        )

    def check_consumption(
        self,
        plan: EnergyActionPlan,
        outcome: ConsumptionOutcome,
    ) -> EnforcementDecision:
        """Evaluate actual consumption; return STOP on overrun."""
        if outcome.overrun:
            return EnforcementDecision(
                decision=EnergyDecision.STOP,
                reason=EnforcementReason.RUNTIME_BUDGET_EXCEEDED,
                approval_reason=ApprovalReason.RUNTIME_BUDGET_EXCEEDED,
            )
        return EnforcementDecision(
            decision=EnergyDecision.ALLOW,
            reason=EnforcementReason.WITHIN_BUDGET,
        )

    def check_context_disposition(
        self,
        disposition: ContextDisposition,
    ) -> EnforcementDecision:
        """Map context build outcome to an enforcement decision.

        Required security failures → REJECT (never escalate to budget approval).
        Required budget failures → PENDING_APPROVAL.
        Dispatchable context → ALLOW.
        """
        if disposition.required_security_failure:
            return EnforcementDecision(
                decision=EnergyDecision.REJECT,
                reason=EnforcementReason.SECURITY_POLICY_REJECTION,
            )
        if disposition.required_budget_failure:
            return EnforcementDecision(
                decision=EnergyDecision.PENDING_APPROVAL,
                reason=EnforcementReason.CONTEXT_BUDGET_EXCEEDED,
                approval_reason=ApprovalReason.CONTEXT_BUDGET_EXCEEDED,
            )
        return EnforcementDecision(
            decision=EnergyDecision.ALLOW,
            reason=EnforcementReason.WITHIN_BUDGET,
        )

    def check_retry_limit(self, plan: EnergyActionPlan) -> EnforcementDecision:
        """Return STOP when retry_index >= max_retries (0 max_retries = unlimited)."""
        if plan.max_retries > 0 and plan.retry_index >= plan.max_retries:
            return EnforcementDecision(
                decision=EnergyDecision.STOP,
                reason=EnforcementReason.RETRY_LIMIT_EXCEEDED,
                approval_reason=ApprovalReason.RETRY_LIMIT_EXCEEDED,
            )
        return EnforcementDecision(
            decision=EnergyDecision.ALLOW,
            reason=EnforcementReason.WITHIN_BUDGET,
        )
