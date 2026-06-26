"""Pure-node tests: determinism, no input mutation, replay semantics (CP2)."""

from __future__ import annotations

import copy

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import GateType
from ant_orchestrator.workflows.decision_gate import (
    DecisionGateOutcome,
    DecisionGateReason,
    DecisionGateResult,
)
from ant_orchestrator.workflows.nodes import (
    PHASE_AWAIT_APPROVAL,
    PHASE_FAILED,
    context_node,
    decision_node,
    evaluate_review,
    evaluate_validation,
    plan_node,
    prepare_approval_intent,
)
from ant_orchestrator.workflows.state import new_graph_state


def _state() -> dict[str, object]:
    return dict(new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=2))


def test_plan_node_is_deterministic_and_pure() -> None:
    state = _state()
    snapshot = copy.deepcopy(state)
    out1 = plan_node(state)
    out2 = plan_node(state)
    assert out1 == out2
    assert state == snapshot  # input not mutated
    assert out1["plan"] == {"goal": "goal:T1", "plan_revision": 0}


def test_context_node_uses_plan_revision() -> None:
    state = _state()
    state["plan"] = {"goal": "goal:T1", "plan_revision": 1}
    out = context_node(state)
    assert out["context_ref"] == "ctx:R1:1"


def test_decision_node_maps_outcome_to_phase() -> None:
    deny = DecisionGateResult(
        outcome=DecisionGateOutcome.DENY,
        reason=DecisionGateReason.ENERGY_SECURITY_REJECTED,
        gate_type=GateType.ENERGY_BUDGET,
    )
    out = decision_node(_state(), deny)
    assert out["phase"] == PHASE_FAILED
    assert out["error_summary"] == DecisionGateReason.ENERGY_SECURITY_REJECTED.value


def test_prepare_intent_increments_once_then_replay_is_noop() -> None:
    state = _state()
    snapshot = copy.deepcopy(state)
    delta1 = prepare_approval_intent(
        state, gate_type=GateType.RETRY_LIMIT, logical_action_id="act-1"
    )
    assert state == snapshot  # pure
    assert delta1["approval_gate_sequence"] == 1
    assert delta1["phase"] == PHASE_AWAIT_APPROVAL

    state1 = {**state, **delta1}
    replay = prepare_approval_intent(
        state1, gate_type=GateType.RETRY_LIMIT, logical_action_id="act-1"
    )
    assert replay == {}  # same occurrence -> no increment, stable id


def test_prepare_intent_new_occurrence_increments() -> None:
    state = _state()
    delta1 = prepare_approval_intent(
        state, gate_type=GateType.RETRY_LIMIT, logical_action_id="act-1"
    )
    state1 = {**state, **delta1}
    delta2 = prepare_approval_intent(
        state1, gate_type=GateType.ENERGY_BUDGET, logical_action_id="act-1"
    )
    assert delta2["approval_gate_sequence"] == 2


def test_validation_and_review_mapping_is_deterministic() -> None:
    state = _state()
    v = evaluate_validation(state, WorkerOutcome.RETRYABLE_FAILURE)
    assert v["validation_result"] == {"status": "retryable", "reason_code": "retryable_failure"}
    r = evaluate_review(state, WorkerOutcome.REVIEW_REGROUP)
    assert r["review_result"] == {"status": "regroup", "reason_code": "review_regroup"}
    assert evaluate_validation(state, WorkerOutcome.SUCCESS) == evaluate_validation(
        state, WorkerOutcome.SUCCESS
    )
