"""Workflow graph with the real human-approval interrupt path (PHASE_4_PLAN D.2).

LangGraph lives only in this module. The CP3 ``gate_blocked`` placeholder is gone:
``REQUIRE_APPROVAL`` and every escalation now fold into a single
``prepare_intent`` → ``await_approval`` path that raises a LangGraph ``interrupt``.
On resume, APPROVE follows the approved continuation, while REJECT/CANCEL route to
fixed terminal markers. Terminal nodes only emit a ``final_outcome`` marker — they
never mutate Task/WorkflowRun/Approval (that is the finalizers' job, off-graph).
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ant_orchestrator.application.ports.worker import WorkerExecutionPort
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.decision_gate import DecisionGateOutcome, DecisionGatePolicy
from ant_orchestrator.workflows.graph_support import (
    PHASE_AWAIT_APPROVAL,
    PHASE_CANCELLED,
    PHASE_COMPLETED,
    PHASE_EXECUTE,
    PHASE_FAILED,
    PHASE_PERSIST,
    PHASE_PLAN,
    PHASE_PREPARE_INTENT,
    PHASE_REJECTED,
    PHASE_REVIEW,
    PHASE_VALIDATE,
    apply_approval_delta,
    build_escalation_payload,
    intent_from_state,
    intent_to_state,
    last_outcome,
    mark_pending_gate,
    phase_of,
    read_pending_gate,
    route_after_review,
    route_after_validation,
    status_of,
)
from ant_orchestrator.workflows.nodes import (
    context_node,
    decision_node,
    evaluate_review,
    evaluate_validation,
    plan_node,
    prepare_approval_intent,
)
from ant_orchestrator.workflows.state import GraphState

__all__ = ["WORKFLOW_DEFINITION_VERSION", "build_workflow_graph"]

NODE_PLAN = "plan"
NODE_CONTEXT = "context"
NODE_DECISION = "decision"
NODE_EXECUTE = "execute_stub"
NODE_VALIDATE = "validate"
NODE_REVIEW = "review"
NODE_PREPARE_INTENT = "prepare_intent"
NODE_AWAIT_APPROVAL = "await_approval"
NODE_PERSIST = "persist_handoff"
NODE_FAILED = "failed"
NODE_REJECTED = "rejected"
NODE_CANCELLED = "cancelled"

_OUTCOME_KEY = "last_outcome"


def _apply_route(delta: dict[str, object], state: GraphState, route: dict[str, object]) -> None:
    """Merge a routing result into a node delta, folding any escalation gate."""
    gate_type = route.pop("gate_type", None)
    continuation = route.pop("continuation", None)
    delta.update(route)
    if gate_type is not None:
        action_intent = dict(state.get("action_intent") or {})
        mark_pending_gate(
            action_intent,
            gate_type=gate_type,  # type: ignore[arg-type]
            continuation=continuation,  # type: ignore[arg-type]
            reason="escalation",
        )
        delta["action_intent"] = action_intent


def build_workflow_graph(
    worker: WorkerExecutionPort,
    policy: DecisionGatePolicy,
    attempt_orchestrator: AttemptOrchestrator | None = None,
) -> StateGraph:
    """Build (but do not compile) the CP5 graph with attempt orchestration and RetryGrant."""

    def decision(state: GraphState) -> dict[str, object]:
        intent = intent_from_state(state)
        if intent.requires_unsafe_command:
            result = policy.evaluate_unsafe_command(intent)
        else:
            result = policy.evaluate_significant_write(intent)
        delta = decision_node(state, result)
        action_intent = intent_to_state(intent)
        if result.outcome is DecisionGateOutcome.REQUIRE_APPROVAL:
            mark_pending_gate(
                action_intent,
                gate_type=result.gate_type,
                continuation=result.approved_continuation,
                reason=result.reason.value,
            )
        delta["action_intent"] = action_intent
        return delta

    def execute_stub(state: GraphState) -> dict[str, object]:
        intent = intent_from_state(state)
        run_id = str(state.get("workflow_run_id", ""))
        attempt_id: str | None = None
        if attempt_orchestrator is not None:
            attempt_id = attempt_orchestrator.before_execute(run_id, intent.logical_action_id)
        result = worker.execute(intent)
        if attempt_orchestrator is not None and attempt_id is not None:
            attempt_orchestrator.after_execute(attempt_id, result.outcome)
        action_intent = dict(state.get("action_intent") or {})
        action_intent[_OUTCOME_KEY] = result.outcome.value
        evidence = list(state.get("evidence_refs") or [])
        evidence.extend(result.evidence_refs)
        return {
            "action_intent": action_intent,
            "evidence_refs": evidence,
            "phase": PHASE_VALIDATE,
            "execution_attempt_ref": attempt_id,
        }

    def validate(state: GraphState) -> dict[str, object]:
        delta = dict(evaluate_validation(state, last_outcome(state)))
        route = route_after_validation(state, status_of(delta, "validation_result"))
        _apply_route(delta, state, route)
        return delta

    def review(state: GraphState) -> dict[str, object]:
        delta = dict(evaluate_review(state, last_outcome(state)))
        _apply_route(delta, state, route_after_review(state, status_of(delta, "review_result")))
        return delta

    def prepare_intent(state: GraphState) -> dict[str, object]:
        action_intent = dict(state.get("action_intent") or {})
        gate_type, continuation, reason = read_pending_gate(action_intent)
        logical_action_id = str(
            action_intent.get("logical_action_id") or f"{state.get('task_id', '')}-act"
        )
        payload = build_escalation_payload(state, gate_type, reason)
        delta = dict(
            prepare_approval_intent(
                state,
                gate_type=gate_type,
                logical_action_id=logical_action_id,
                payload=payload,
                approved_continuation=continuation,
            )
        )
        delta.setdefault("phase", PHASE_AWAIT_APPROVAL)
        return delta

    def await_approval(state: GraphState) -> dict[str, object]:
        intent = dict(state.get("approval_intent") or {})
        decision_token = str(interrupt(intent))
        delta = apply_approval_delta(intent, decision_token, state)
        delta["approval_decision"] = {"decision": decision_token}
        # Clear approval_intent so the next prepare_intent treats it as a new occurrence.
        delta["approval_intent"] = None
        return delta

    graph = StateGraph(GraphState)
    graph.add_node(NODE_PLAN, plan_node)
    graph.add_node(NODE_CONTEXT, context_node)
    graph.add_node(NODE_DECISION, decision)
    graph.add_node(NODE_EXECUTE, execute_stub)
    graph.add_node(NODE_VALIDATE, validate)
    graph.add_node(NODE_REVIEW, review)
    graph.add_node(NODE_PREPARE_INTENT, prepare_intent)
    graph.add_node(NODE_AWAIT_APPROVAL, await_approval)
    graph.add_node(
        NODE_PERSIST, lambda state: {"final_outcome": "completed", "phase": PHASE_COMPLETED}
    )
    graph.add_node(NODE_FAILED, lambda state: {"final_outcome": "failed"})
    graph.add_node(NODE_REJECTED, lambda state: {"final_outcome": "rejected"})
    graph.add_node(NODE_CANCELLED, lambda state: {"final_outcome": "cancelled"})

    _wire_edges(graph)
    return graph


def _wire_edges(graph: StateGraph) -> None:
    graph.add_edge(START, NODE_PLAN)
    graph.add_edge(NODE_PLAN, NODE_CONTEXT)
    graph.add_edge(NODE_CONTEXT, NODE_DECISION)
    graph.add_conditional_edges(
        NODE_DECISION,
        phase_of,
        {
            PHASE_EXECUTE: NODE_EXECUTE,
            PHASE_PREPARE_INTENT: NODE_PREPARE_INTENT,
            PHASE_FAILED: NODE_FAILED,
        },
    )
    graph.add_edge(NODE_PREPARE_INTENT, NODE_AWAIT_APPROVAL)
    graph.add_conditional_edges(
        NODE_AWAIT_APPROVAL,
        phase_of,
        {
            PHASE_EXECUTE: NODE_EXECUTE,
            PHASE_PLAN: NODE_PLAN,
            PHASE_PERSIST: NODE_PERSIST,
            PHASE_REJECTED: NODE_REJECTED,
            PHASE_CANCELLED: NODE_CANCELLED,
            PHASE_FAILED: NODE_FAILED,  # RetryGrant bound fail-closed
        },
    )
    graph.add_edge(NODE_EXECUTE, NODE_VALIDATE)
    graph.add_conditional_edges(
        NODE_VALIDATE,
        phase_of,
        {
            PHASE_REVIEW: NODE_REVIEW,
            PHASE_EXECUTE: NODE_EXECUTE,
            PHASE_PLAN: NODE_PLAN,
            PHASE_FAILED: NODE_FAILED,
            PHASE_PREPARE_INTENT: NODE_PREPARE_INTENT,
        },
    )
    graph.add_conditional_edges(
        NODE_REVIEW,
        phase_of,
        {
            PHASE_PERSIST: NODE_PERSIST,
            PHASE_PLAN: NODE_PLAN,
            PHASE_PREPARE_INTENT: NODE_PREPARE_INTENT,
        },
    )
    graph.add_edge(NODE_PERSIST, END)
    graph.add_edge(NODE_FAILED, END)
    graph.add_edge(NODE_REJECTED, END)
    graph.add_edge(NODE_CANCELLED, END)
