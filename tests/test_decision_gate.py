"""DecisionGatePolicy tests — ALLOW/REQUIRE_APPROVAL/DENY per gate (CP2)."""

from __future__ import annotations

from types import MappingProxyType

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    CapabilityKind,
    EnergyActionPlan,
    EnergyBudget,
    QualityRequirement,
    ResourceKind,
)
from ant_orchestrator.application.ports.worker import WorkerActionIntent
from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.workflows.decision_gate import (
    DecisionGateOutcome,
    DecisionGatePolicy,
    DecisionGateReason,
)

_POLICY = DecisionGatePolicy(EnforcementPolicy())


def _plan(*, required: frozenset[ResourceKind], retry_index: int = 0, max_retries: int = 0):
    return EnergyActionPlan(
        task_id=TaskId("T1"),
        correlation_id=CorrelationId("corr-1"),
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=CapabilityKind.LLM_INFERENCE,
        estimated_resources=MappingProxyType({ResourceKind.TOKENS: 100}),
        required_resources=required,
        deterministic_available=False,
        cache_valid=False,
        local_available=True,
        cloud_available=False,
        allow_auto_cloud=False,
        quality_requirement=QualityRequirement.ANY,
        retry_index=retry_index,
        max_retries=max_retries,
    )


def _intent(*, write: bool = False, unsafe: bool = False) -> WorkerActionIntent:
    return WorkerActionIntent(
        logical_action_id="act-1",
        summary="do the thing",
        requires_significant_write=write,
        requires_unsafe_command=unsafe,
    )


def test_significant_write_allow_and_require_approval() -> None:
    allow = _POLICY.evaluate_significant_write(_intent(write=False))
    assert allow.outcome is DecisionGateOutcome.ALLOW
    assert allow.reason is DecisionGateReason.NO_SIGNIFICANT_WRITE
    req = _POLICY.evaluate_significant_write(_intent(write=True))
    assert req.outcome is DecisionGateOutcome.REQUIRE_APPROVAL
    assert req.approved_continuation is ApprovalContinuation.EXECUTE


def test_unsafe_command_allow_and_require_approval() -> None:
    assert (
        _POLICY.evaluate_unsafe_command(_intent(unsafe=False)).outcome is DecisionGateOutcome.ALLOW
    )
    req = _POLICY.evaluate_unsafe_command(_intent(unsafe=True))
    assert req.outcome is DecisionGateOutcome.REQUIRE_APPROVAL
    assert req.gate_type is GateType.UNSAFE_COMMAND


def test_energy_budget_governed_allows() -> None:
    budget = EnergyBudget({ResourceKind.TOKENS: 1000})
    result = _POLICY.evaluate_energy_budget(
        _plan(required=frozenset({ResourceKind.TOKENS})), budget
    )
    assert result.outcome is DecisionGateOutcome.ALLOW
    assert result.reason is DecisionGateReason.ENERGY_WITHIN_BUDGET


def test_energy_budget_missing_limit_requires_approval() -> None:
    budget = EnergyBudget({ResourceKind.TOKENS: 1000})
    plan = _plan(required=frozenset({ResourceKind.API_CALLS}))  # API_CALLS ungoverned
    result = _POLICY.evaluate_energy_budget(plan, budget)
    assert result.outcome is DecisionGateOutcome.REQUIRE_APPROVAL
    assert result.reason is DecisionGateReason.ENERGY_REQUIRES_APPROVAL
    assert result.approved_continuation is ApprovalContinuation.EXECUTE


def test_retry_limit_within_and_exceeded() -> None:
    within = _POLICY.evaluate_retry_limit(
        _plan(required=frozenset({ResourceKind.TOKENS}), retry_index=1, max_retries=3)
    )
    assert within.outcome is DecisionGateOutcome.ALLOW
    exceeded = _POLICY.evaluate_retry_limit(
        _plan(required=frozenset({ResourceKind.TOKENS}), retry_index=3, max_retries=3)
    )
    assert exceeded.outcome is DecisionGateOutcome.REQUIRE_APPROVAL
    assert exceeded.gate_type is GateType.RETRY_LIMIT


def test_scope_change_requires_approval_with_replan() -> None:
    result = _POLICY.evaluate_scope_change()
    assert result.outcome is DecisionGateOutcome.REQUIRE_APPROVAL
    assert result.approved_continuation is ApprovalContinuation.REPLAN


def test_gate_decisions_are_deterministic() -> None:
    budget = EnergyBudget({ResourceKind.TOKENS: 1000})
    plan = _plan(required=frozenset({ResourceKind.TOKENS}))
    first = _POLICY.evaluate_energy_budget(plan, budget)
    second = _POLICY.evaluate_energy_budget(plan, budget)
    assert first == second
