"""CP8 routing policy tests — pure route selection decisions."""

from __future__ import annotations

from types import MappingProxyType

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    CapabilityKind,
    EnergyActionPlan,
    EnergyBudget,
    EnergyDecision,
    QualityRequirement,
    ResourceKind,
    RoutingReason,
)
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.energy.routing import RoutingPolicy

_POLICY = RoutingPolicy()
_TASK = TaskId("task-1")
_CID = CorrelationId("corr-1")
_BUDGET = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 10})


def _plan(
    *,
    cap: CapabilityKind = CapabilityKind.LLM_INFERENCE,
    det_avail: bool = False,
    cache_valid: bool = False,
    local_avail: bool = True,
    cloud_avail: bool = False,
    allow_cloud: bool = False,
    quality: QualityRequirement = QualityRequirement.ANY,
    required: frozenset[ResourceKind] | None = None,
    estimated: dict[ResourceKind, int] | None = None,
    downgrade: dict[ResourceKind, int] | None = None,
) -> EnergyActionPlan:
    return EnergyActionPlan(
        task_id=_TASK,
        correlation_id=_CID,
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=cap,
        estimated_resources=MappingProxyType(estimated or {ResourceKind.TOKENS: 100}),
        required_resources=required if required is not None else frozenset({ResourceKind.TOKENS}),
        deterministic_available=det_avail,
        cache_valid=cache_valid,
        local_available=local_avail,
        cloud_available=cloud_avail,
        allow_auto_cloud=allow_cloud,
        quality_requirement=quality,
        downgrade_resources=MappingProxyType(downgrade) if downgrade else None,
    )


def _avail(tokens: int = 1000, api: int = 10) -> dict[ResourceKind, int | None]:
    return {ResourceKind.TOKENS: tokens, ResourceKind.API_CALLS: api}


class TestDeterminsticRouting:
    def test_deterministic_eligible(self) -> None:
        plan = _plan(det_avail=True, cap=CapabilityKind.DETERMINISTIC)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.USE_DETERMINISTIC_TOOL
        assert d.reason is RoutingReason.DETERMINISTIC_AVAILABLE

    def test_deterministic_wrong_capability_skipped(self) -> None:
        plan = _plan(det_avail=True, cap=CapabilityKind.LLM_INFERENCE)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is not EnergyDecision.USE_DETERMINISTIC_TOOL

    def test_deterministic_not_available_skipped(self) -> None:
        plan = _plan(det_avail=False, cap=CapabilityKind.DETERMINISTIC)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is not EnergyDecision.USE_DETERMINISTIC_TOOL

    def test_deterministic_priority_over_cache(self) -> None:
        plan = _plan(det_avail=True, cache_valid=True, cap=CapabilityKind.DETERMINISTIC)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.USE_DETERMINISTIC_TOOL


class TestCacheRouting:
    def test_cache_valid_use_cache(self) -> None:
        plan = _plan(cache_valid=True)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.USE_CACHE
        assert d.reason is RoutingReason.CACHE_HIT

    def test_cache_invalid_skipped(self) -> None:
        plan = _plan(cache_valid=False)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is not EnergyDecision.USE_CACHE

    def test_cache_any_capability(self) -> None:
        for cap in (CapabilityKind.LLM_INFERENCE, CapabilityKind.CODE_EXECUTION):
            plan = _plan(cache_valid=True, cap=cap)
            d = _POLICY.route(plan, _BUDGET, _avail())
            assert d.decision is EnergyDecision.USE_CACHE


class TestLocalRouting:
    def test_local_available_capable_route_local(self) -> None:
        plan = _plan(local_avail=True)
        d = _POLICY.route(plan, _BUDGET, _avail(1000))
        assert d.decision is EnergyDecision.ROUTE_LOCAL
        assert d.reason is RoutingReason.LOCAL_CAPABLE

    def test_local_unavailable_falls_to_cloud_check(self) -> None:
        plan = _plan(local_avail=False, cloud_avail=True)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.CLOUD_REQUIRES_APPROVAL

    def test_local_unavailable_no_cloud_reject(self) -> None:
        plan = _plan(local_avail=False, cloud_avail=False)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.REJECT
        assert d.reason is RoutingReason.LOCAL_UNAVAILABLE

    def test_budget_insufficient_no_cloud(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 500})
        d = _POLICY.route(plan, _BUDGET, _avail(tokens=100))
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.BUDGET_INSUFFICIENT

    def test_budget_insufficient_fallback_cloud(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 500}, cloud_avail=True)
        d = _POLICY.route(plan, _BUDGET, _avail(tokens=100))
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.CLOUD_REQUIRES_APPROVAL

    def test_exact_budget_boundary_local(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 1000})
        d = _POLICY.route(plan, _BUDGET, _avail(1000))
        assert d.decision is EnergyDecision.ROUTE_LOCAL

    def test_boundary_plus_one_insufficient(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 1001})
        d = _POLICY.route(plan, _BUDGET, _avail(1000))
        assert d.decision is EnergyDecision.PENDING_APPROVAL

    def test_missing_required_budget_pending(self) -> None:
        plan = _plan(
            required=frozenset({ResourceKind.RETRIES}),
            estimated={ResourceKind.TOKENS: 100},
        )
        avail: dict[ResourceKind, int | None] = {
            ResourceKind.TOKENS: 1000,
            ResourceKind.RETRIES: None,
        }
        d = _POLICY.route(plan, _BUDGET, avail)
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.MISSING_REQUIRED_BUDGET


class TestCloudRouting:
    def test_cloud_always_pending_approval(self) -> None:
        plan = _plan(local_avail=False, cloud_avail=True)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.CLOUD_REQUIRES_APPROVAL

    def test_allow_auto_cloud_false_still_pending(self) -> None:
        plan = _plan(local_avail=False, cloud_avail=True, allow_cloud=False)
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.PENDING_APPROVAL

    def test_quality_cloud_required_skips_local(self) -> None:
        plan = _plan(local_avail=True, cloud_avail=True, quality=QualityRequirement.CLOUD_REQUIRED)
        d = _POLICY.route(plan, _BUDGET, _avail(1000))
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.CLOUD_REQUIRES_APPROVAL

    def test_quality_cloud_no_cloud_reject(self) -> None:
        plan = _plan(local_avail=True, cloud_avail=False, quality=QualityRequirement.CLOUD_REQUIRED)
        d = _POLICY.route(plan, _BUDGET, _avail(1000))
        assert d.decision is EnergyDecision.REJECT


class TestNoEligibleRoute:
    def test_no_route_reject(self) -> None:
        plan = _plan(
            cap=CapabilityKind.DETERMINISTIC,
            det_avail=False,
            cache_valid=False,
            local_avail=False,
            cloud_avail=False,
        )
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.REJECT

    def test_capability_not_model_no_route(self) -> None:
        plan = _plan(
            cap=CapabilityKind.CACHE_ONLY,
            det_avail=False,
            cache_valid=False,
            local_avail=True,
        )
        d = _POLICY.route(plan, _BUDGET, _avail())
        assert d.decision is EnergyDecision.REJECT
        assert d.reason is RoutingReason.CAPABILITY_REQUIREMENT


class TestDowngradeRouting:
    def test_budget_insufficient_downgrade_available(self) -> None:
        plan = _plan(
            estimated={ResourceKind.TOKENS: 800},
            required=frozenset({ResourceKind.TOKENS}),
            downgrade={ResourceKind.TOKENS: 300},
        )
        d = _POLICY.route(plan, _BUDGET, _avail(tokens=500))
        assert d.decision is EnergyDecision.DOWNGRADE
        assert d.reason is RoutingReason.DOWNGRADE_AVAILABLE
        assert d.downgrade_resources is not None
        assert d.downgrade_resources[ResourceKind.TOKENS] == 300

    def test_no_downgrade_candidate_budget_insufficient(self) -> None:
        plan = _plan(estimated={ResourceKind.TOKENS: 800})
        d = _POLICY.route(plan, _BUDGET, _avail(tokens=500))
        assert d.decision is EnergyDecision.PENDING_APPROVAL
        assert d.reason is RoutingReason.BUDGET_INSUFFICIENT
