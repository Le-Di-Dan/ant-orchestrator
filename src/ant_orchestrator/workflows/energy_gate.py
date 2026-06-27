"""Energy-budget gate evaluation for the workflow decision node (PHASE_4_PLAN C.8).

A structured action intent that declares ``requires_energy_approval`` is checked
against the *same* Phase 3 ``EnforcementPolicy`` the rest of the system uses — no
parallel energy policy is introduced. Phase 4 wires no governing budget into the
graph, so an energy-governed action with no covered limit is classified
``MISSING_REQUIRED_BUDGET`` → REQUIRE_APPROVAL (fail-closed), exactly as the policy
dictates; a future budget that covers the resource would map to ALLOW unchanged.
"""

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
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy, DecisionGateResult

# Phase 4 governs no workflow budget yet: an energy-governed action is evaluated
# against an empty budget, so a required resource has no covered limit.
_EMPTY_BUDGET = EnergyBudget({})
_ENERGY_CORRELATION_PREFIX = "energy-gate-"


def _governed_plan(task_id: str) -> EnergyActionPlan:
    """A minimal, sanitized plan that requires one governed resource (no secrets)."""
    return EnergyActionPlan(
        task_id=TaskId(task_id),
        correlation_id=CorrelationId(f"{_ENERGY_CORRELATION_PREFIX}{task_id}"),
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=CapabilityKind.LLM_INFERENCE,
        estimated_resources=MappingProxyType({ResourceKind.TOKENS: 1}),
        required_resources=frozenset({ResourceKind.TOKENS}),
        deterministic_available=False,
        cache_valid=False,
        local_available=True,
        cloud_available=False,
        allow_auto_cloud=False,
        quality_requirement=QualityRequirement.ANY,
    )


def evaluate_energy_gate(policy: DecisionGatePolicy, task_id: str) -> DecisionGateResult:
    """Map a structured energy-governed action to a gate decision via EnforcementPolicy."""
    return policy.evaluate_energy_budget(_governed_plan(task_id), _EMPTY_BUDGET)
