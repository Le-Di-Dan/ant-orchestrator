"""CP8 enforcement policy tests — pure budget coverage and overrun decisions."""

from __future__ import annotations

from types import MappingProxyType

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    ApprovalReason,
    BudgetCoverage,
    CapabilityKind,
    ContextDisposition,
    EnergyActionPlan,
    EnergyBudget,
    EnergyDecision,
    EnforcementReason,
    QualityRequirement,
    ResourceKind,
)
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.energy.reservation import ConsumptionOutcome

_POLICY = EnforcementPolicy()
_BUDGET = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 10})
_TASK = TaskId("task-1")
_CID = CorrelationId("corr-1")


def _plan(
    *,
    required: frozenset[ResourceKind] | None = None,
    estimated: dict[ResourceKind, int] | None = None,
    retry_index: int = 0,
    max_retries: int = 0,
    ctx: ContextDisposition | None = None,
    downgrade: dict[ResourceKind, int] | None = None,
) -> EnergyActionPlan:
    return EnergyActionPlan(
        task_id=_TASK,
        correlation_id=_CID,
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=CapabilityKind.LLM_INFERENCE,
        estimated_resources=MappingProxyType(estimated or {ResourceKind.TOKENS: 100}),
        required_resources=required if required is not None else frozenset({ResourceKind.TOKENS}),
        deterministic_available=False,
        cache_valid=False,
        local_available=True,
        cloud_available=False,
        allow_auto_cloud=False,
        quality_requirement=QualityRequirement.ANY,
        context_disposition=ctx,
        retry_index=retry_index,
        max_retries=max_retries,
        downgrade_resources=MappingProxyType(downgrade) if downgrade else None,
    )


def _outcome(overrun: bool, excess: dict[ResourceKind, int]) -> ConsumptionOutcome:
    return ConsumptionOutcome(
        reservation_id="res-1",
        overrun=overrun,
        excess=MappingProxyType(excess),
    )


class TestBudgetCoverage:
    def test_within_budget_allow(self) -> None:
        d = _POLICY.check_budget_coverage(_plan(), _BUDGET)
        assert d.decision is EnergyDecision.ALLOW
        assert d.reason is EnforcementReason.WITHIN_BUDGET
        assert d.coverage is BudgetCoverage.GOVERNED

    def test_missing_required_budget_pending(self) -> None:
        plan = _plan(required=frozenset({ResourceKind.RETRIES}))
        budget = EnergyBudget({ResourceKind.TOKENS: 1000})
        d = _POLICY.check_budget_coverage(plan, budget)
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is EnforcementReason.MISSING_REQUIRED_BUDGET
        assert d.coverage is BudgetCoverage.MISSING_REQUIRED_LIMIT
        assert d.approval_reason is ApprovalReason.BUDGET_INSUFFICIENT

    def test_exact_boundary_allowed(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 1000})
        d = _POLICY.check_budget_coverage(plan, _BUDGET)
        assert d.decision is EnergyDecision.ALLOW

    def test_no_required_resources_allow(self) -> None:
        plan = _plan(required=frozenset(), estimated={})
        d = _POLICY.check_budget_coverage(plan, _BUDGET)
        assert d.decision is EnergyDecision.ALLOW

    def test_multiple_required_all_governed(self) -> None:
        plan = _plan(
            required=frozenset({ResourceKind.TOKENS, ResourceKind.API_CALLS}),
            estimated={ResourceKind.TOKENS: 100, ResourceKind.API_CALLS: 1},
        )
        d = _POLICY.check_budget_coverage(plan, _BUDGET)
        assert d.decision is EnergyDecision.ALLOW

    def test_one_of_multiple_missing_fails(self) -> None:
        plan = _plan(
            required=frozenset({ResourceKind.TOKENS, ResourceKind.RETRIES}),
            estimated={ResourceKind.TOKENS: 100},
        )
        d = _POLICY.check_budget_coverage(plan, _BUDGET)
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.coverage is BudgetCoverage.MISSING_REQUIRED_LIMIT

    def test_empty_budget_missing_required(self) -> None:
        plan = _plan(required=frozenset({ResourceKind.TOKENS}))
        d = _POLICY.check_budget_coverage(plan, EnergyBudget({}))
        assert d.decision is EnergyDecision.PENDING_APPROVAL

    def test_deterministic_no_required_resources(self) -> None:
        plan = _plan(required=frozenset(), estimated={})
        d = _POLICY.check_budget_coverage(plan, EnergyBudget({}))
        assert d.decision is EnergyDecision.ALLOW


class TestConsumptionOverrun:
    def test_no_overrun_allow(self) -> None:
        d = _POLICY.check_consumption(_plan(), _outcome(False, {}))
        assert d.decision is EnergyDecision.ALLOW
        assert d.reason is EnforcementReason.WITHIN_BUDGET

    def test_overrun_stop(self) -> None:
        d = _POLICY.check_consumption(_plan(), _outcome(True, {ResourceKind.TOKENS: 50}))
        assert d.decision is EnergyDecision.STOP
        assert d.reason is EnforcementReason.RUNTIME_BUDGET_EXCEEDED
        assert d.approval_reason is ApprovalReason.RUNTIME_BUDGET_EXCEEDED

    def test_zero_excess_no_overrun(self) -> None:
        d = _POLICY.check_consumption(_plan(), _outcome(False, {ResourceKind.TOKENS: 0}))
        assert d.decision is EnergyDecision.ALLOW

    def test_pure_no_ledger_mutation(self) -> None:
        plan = _plan()
        # Calling multiple times must not change state
        for _ in range(5):
            d = _POLICY.check_consumption(plan, _outcome(False, {}))
            assert d.decision is EnergyDecision.ALLOW


class TestContextDisposition:
    def test_dispatchable_allow(self) -> None:
        ctx = ContextDisposition(
            dispatchable=True, required_budget_failure=False, required_security_failure=False
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.decision is EnergyDecision.ALLOW

    def test_required_budget_failure_pending(self) -> None:
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=True, required_security_failure=False
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is EnforcementReason.CONTEXT_BUDGET_EXCEEDED
        assert d.approval_reason is ApprovalReason.CONTEXT_BUDGET_EXCEEDED

    def test_required_security_failure_reject(self) -> None:
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=False, required_security_failure=True
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.decision is EnergyDecision.REJECT
        assert d.reason is EnforcementReason.SECURITY_POLICY_REJECTION

    def test_security_takes_priority_over_budget(self) -> None:
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=True, required_security_failure=True
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.decision is EnergyDecision.REJECT

    def test_optional_rejection_not_blocked(self) -> None:
        ctx = ContextDisposition(
            dispatchable=True, required_budget_failure=False, required_security_failure=False
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.decision is EnergyDecision.ALLOW

    def test_security_rejection_no_budget_approval(self) -> None:
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=False, required_security_failure=True
        )
        d = _POLICY.check_context_disposition(ctx)
        assert d.approval_reason is None


class TestRetryLimit:
    def test_no_limit_allow(self) -> None:
        plan = _plan(retry_index=10, max_retries=0)
        d = _POLICY.check_retry_limit(plan)
        assert d.decision is EnergyDecision.ALLOW

    def test_within_limit_allow(self) -> None:
        plan = _plan(retry_index=1, max_retries=3)
        d = _POLICY.check_retry_limit(plan)
        assert d.decision is EnergyDecision.ALLOW

    def test_exact_limit_stop(self) -> None:
        plan = _plan(retry_index=3, max_retries=3)
        d = _POLICY.check_retry_limit(plan)
        assert d.decision is EnergyDecision.STOP
        assert d.reason is EnforcementReason.RETRY_LIMIT_EXCEEDED

    def test_over_limit_stop(self) -> None:
        plan = _plan(retry_index=5, max_retries=3)
        d = _POLICY.check_retry_limit(plan)
        assert d.decision is EnergyDecision.STOP

    def test_zero_retry_index_zero_max_allow(self) -> None:
        plan = _plan(retry_index=0, max_retries=0)
        d = _POLICY.check_retry_limit(plan)
        assert d.decision is EnergyDecision.ALLOW
