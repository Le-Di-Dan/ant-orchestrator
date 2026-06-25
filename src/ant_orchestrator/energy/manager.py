"""Energy manager facade — orchestrates routing, reservation, and enforcement (CP8).

Single-process coordinator. **Callers must serialize concurrent calls** — the
underlying ReservationLedger is not thread-safe (see reservation.py).

Flow for model actions:
  context-check → route → enforce-budget-coverage → reserve → pre-audit
  → execute → consume → check-overrun → post-audit → result
"""

from __future__ import annotations

from types import MappingProxyType

from ant_orchestrator.application.ports.audit import AuditSink, CorrelationId
from ant_orchestrator.application.ports.energy import (
    ApprovalConsequence,
    ApprovalReason,
    ApprovalRequest,
    EnergyActionPlan,
    EnergyActionResult,
    EnergyBoundAction,
    EnergyDecision,
    EnergyManagerResult,
    EnforcementReason,
    ResourceKind,
    RoutingReason,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.energy._audit_writer import LocalAuditWriter
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.energy.reservation import ReservationLedger
from ant_orchestrator.energy.routing import RoutingDecision, RoutingPolicy


class EnergyManager:
    """Facade enforcing reserve-before-side-effect and audit ordering.

    Not thread-safe. One instance per serialized execution context.
    """

    def __init__(
        self,
        ledger: ReservationLedger,
        audit_sink: AuditSink,
        routing_policy: RoutingPolicy,
        enforcement_policy: EnforcementPolicy,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._ledger = ledger
        self._routing = routing_policy
        self._enforcement = enforcement_policy
        self._clock = clock
        self._ids = id_gen
        self._auditor = LocalAuditWriter(audit_sink, clock)

    def execute(
        self,
        plan: EnergyActionPlan,
        *,
        model_action: EnergyBoundAction | None = None,
        deterministic_action: EnergyBoundAction | None = None,
        cache_action: EnergyBoundAction | None = None,
    ) -> EnergyManagerResult:
        """Guarded execution: gate, route, reserve, audit, run, consume."""
        cid = plan.correlation_id

        # 1. Context disposition — before routing
        if plan.context_disposition is not None:
            ctx = self._enforcement.check_context_disposition(plan.context_disposition)
            if ctx.decision is not EnergyDecision.ALLOW:
                approval = None
                if ctx.decision is EnergyDecision.PENDING_APPROVAL and ctx.approval_reason:
                    approval = self._build_approval(
                        plan, ctx.approval_reason, {}, EnergyDecision.ROUTE_LOCAL
                    )
                return EnergyManagerResult(
                    decision=ctx.decision,
                    reason=ctx.reason,
                    approval_request=approval,
                )

        # 2. Retry limit
        retry_check = self._enforcement.check_retry_limit(plan)
        if retry_check.decision is not EnergyDecision.ALLOW:
            approval = None
            if retry_check.approval_reason:
                approval = self._build_approval(
                    plan, retry_check.approval_reason, {}, EnergyDecision.ROUTE_LOCAL
                )
            return EnergyManagerResult(
                decision=retry_check.decision,
                reason=retry_check.reason,
                approval_request=approval,
            )

        # 3. Routing
        available = self._available_snapshot(plan)
        routing = self._routing.route(plan, self._ledger.budget, available)

        # 4. Downgrade (one-time, inline)
        if routing.decision is EnergyDecision.DOWNGRADE and routing.downgrade_resources is not None:
            downgraded = plan.with_estimated_resources(routing.downgrade_resources)
            available2 = self._available_snapshot(downgraded)
            routing = self._routing.route(downgraded, self._ledger.budget, available2)
            plan = downgraded

        # 5. Non-model routes
        if routing.decision is EnergyDecision.USE_DETERMINISTIC_TOOL:
            result = (
                deterministic_action.execute()
                if deterministic_action
                else EnergyActionResult(actual=MappingProxyType({}), side_effect_started=False)
            )
            return EnergyManagerResult(
                decision=EnergyDecision.USE_DETERMINISTIC_TOOL,
                reason=RoutingReason.DETERMINISTIC_AVAILABLE,
                action_result=result,
            )

        if routing.decision is EnergyDecision.USE_CACHE:
            result = (
                cache_action.execute()
                if cache_action
                else EnergyActionResult(actual=MappingProxyType({}), side_effect_started=False)
            )
            return EnergyManagerResult(
                decision=EnergyDecision.USE_CACHE,
                reason=RoutingReason.CACHE_HIT,
                action_result=result,
            )

        if routing.decision is EnergyDecision.PENDING_APPROVAL:
            approval = self._build_approval_from_routing(plan, routing, available)
            return EnergyManagerResult(
                decision=EnergyDecision.PENDING_APPROVAL,
                reason=routing.reason,
                approval_request=approval,
            )

        if routing.decision is EnergyDecision.REJECT:
            return EnergyManagerResult(decision=EnergyDecision.REJECT, reason=routing.reason)

        # 6. ROUTE_LOCAL — enforce budget coverage, reserve, audit, execute
        if routing.decision is EnergyDecision.ROUTE_LOCAL:
            return self._execute_local(plan, cid, model_action, routing)

        return EnergyManagerResult(
            decision=EnergyDecision.REJECT, reason=RoutingReason.ROUTE_NOT_ELIGIBLE
        )

    # --- local execution ---

    def _execute_local(
        self,
        plan: EnergyActionPlan,
        cid: CorrelationId,
        model_action: EnergyBoundAction | None,
        routing: RoutingDecision,
    ) -> EnergyManagerResult:
        budget = self._ledger.budget

        enforcement = self._enforcement.check_budget_coverage(plan, budget)
        if enforcement.decision is not EnergyDecision.ALLOW:
            approval_reason = enforcement.approval_reason or ApprovalReason.BUDGET_INSUFFICIENT
            approval = self._build_approval(plan, approval_reason, {}, EnergyDecision.ROUTE_LOCAL)
            return EnergyManagerResult(
                decision=enforcement.decision,
                reason=enforcement.reason,
                approval_request=approval,
            )

        try:
            reservation = self._ledger.reserve(dict(plan.estimated_resources))
        except Exception:
            return EnergyManagerResult(
                decision=EnergyDecision.PENDING_APPROVAL,
                reason=EnforcementReason.RESERVATION_REJECTED,
                approval_request=self._build_approval(
                    plan, ApprovalReason.BUDGET_INSUFFICIENT, {}, EnergyDecision.ROUTE_LOCAL
                ),
            )

        if not self._auditor.pre_execute(plan, cid, reservation):
            self._safe_release(reservation.id)
            return EnergyManagerResult(
                decision=EnergyDecision.REJECT,
                reason=EnforcementReason.RESERVATION_REJECTED,
                reservation_id=reservation.id,
                audit_failure=True,
            )

        if model_action is None:
            self._safe_release(reservation.id)
            return EnergyManagerResult(
                decision=EnergyDecision.ALLOW,
                reason=RoutingReason.LOCAL_CAPABLE,
                reservation_id=reservation.id,
            )

        try:
            action_result = model_action.execute()
        except Exception:
            self._safe_release(reservation.id)
            return EnergyManagerResult(
                decision=EnergyDecision.REJECT,
                reason=EnforcementReason.RESERVATION_REJECTED,
                reservation_id=reservation.id,
            )

        outcome = self._ledger.consume(reservation.id, dict(action_result.actual))
        enforcement2 = self._enforcement.check_consumption(plan, outcome)
        audit_failure = not self._auditor.post_execute(
            plan, cid, reservation, action_result, enforcement2
        )

        if enforcement2.decision is EnergyDecision.STOP:
            additional = {k: v for k, v in outcome.excess.items() if v > 0}
            approval = self._build_approval(
                plan, ApprovalReason.RUNTIME_BUDGET_EXCEEDED, additional, EnergyDecision.ROUTE_LOCAL
            )
            return EnergyManagerResult(
                decision=EnergyDecision.STOP,
                reason=EnforcementReason.RUNTIME_BUDGET_EXCEEDED,
                approval_request=approval,
                action_result=action_result,
                reservation_id=reservation.id,
                audit_failure=audit_failure,
            )

        return EnergyManagerResult(
            decision=EnergyDecision.ALLOW,
            reason=RoutingReason.LOCAL_CAPABLE,
            action_result=action_result,
            reservation_id=reservation.id,
            audit_failure=audit_failure,
        )

    # --- helpers ---

    def _available_snapshot(self, plan: EnergyActionPlan) -> dict[ResourceKind, int | None]:
        kinds = set(plan.required_resources) | set(plan.estimated_resources.keys())
        return {k: self._ledger.available(k) for k in kinds}

    def _safe_release(self, reservation_id: str) -> None:
        try:
            self._ledger.release(reservation_id)
        except Exception:
            pass

    def _build_approval(
        self,
        plan: EnergyActionPlan,
        reason: ApprovalReason,
        additional: dict[ResourceKind, int],
        proposed: EnergyDecision,
    ) -> ApprovalRequest:
        return ApprovalRequest(
            task_id=plan.task_id,
            correlation_id=plan.correlation_id,
            action_kind=plan.action_kind,
            current_budget=self._ledger.budget,
            required_additional=MappingProxyType(additional),
            proposed_route=proposed,
            reason=reason,
            alternatives_tried=(),
            consequence_if_denied=ApprovalConsequence.ACTION_REJECTED,
            created_at=self._clock.now(),
        )

    def _build_approval_from_routing(
        self,
        plan: EnergyActionPlan,
        routing: RoutingDecision,
        available: dict[ResourceKind, int | None],
    ) -> ApprovalRequest:
        additional: dict[ResourceKind, int] = {}
        for kind in plan.required_resources:
            avail = available.get(kind)
            estimated = plan.estimated_resources.get(kind, 0)
            if avail is None:
                additional[kind] = estimated
            elif estimated > avail:
                additional[kind] = estimated - avail

        reason_map = {
            RoutingReason.CLOUD_REQUIRES_APPROVAL: ApprovalReason.CLOUD_REQUIRES_APPROVAL,
            RoutingReason.MISSING_REQUIRED_BUDGET: ApprovalReason.BUDGET_INSUFFICIENT,
            RoutingReason.BUDGET_INSUFFICIENT: ApprovalReason.BUDGET_INSUFFICIENT,
            RoutingReason.QUALITY_REQUIREMENT: ApprovalReason.CLOUD_REQUIRES_APPROVAL,
            RoutingReason.CONTEXT_BUDGET_EXCEEDED: ApprovalReason.CONTEXT_BUDGET_EXCEEDED,
            RoutingReason.RETRY_LIMIT_EXCEEDED: ApprovalReason.RETRY_LIMIT_EXCEEDED,
        }
        approval_reason = reason_map.get(routing.reason, ApprovalReason.BUDGET_INSUFFICIENT)
        is_cloud = routing.reason is RoutingReason.CLOUD_REQUIRES_APPROVAL
        proposed = EnergyDecision.ESCALATE_CLOUD if is_cloud else EnergyDecision.ROUTE_LOCAL
        return self._build_approval(plan, approval_reason, additional, proposed)
