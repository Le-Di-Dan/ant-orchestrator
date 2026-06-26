"""Walking-skeleton workflow graph (PHASE_4_PLAN C.1/D.2). LangGraph lives only here.

Wires the CP2 pure contracts (nodes, router, gate policy) into a ``StateGraph`` with
explicit conditional edges. Concrete node names exist only in this module. CP3 is the
happy path (gate ALLOW): no ``interrupt()`` / approval orchestration — REQUIRE_APPROVAL
and escalations terminate at a ``gate_blocked`` placeholder that CP4 will replace.
"""

from __future__ import annotations

from collections.abc import Mapping

from langgraph.graph import END, START, StateGraph

from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionPort,
    WorkerOutcome,
)
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.nodes import (
    PHASE_EXECUTE,
    PHASE_FAILED,
    PHASE_PLAN,
    PHASE_PREPARE_INTENT,
    PHASE_REVIEW,
    PHASE_VALIDATE,
    context_node,
    decision_node,
    evaluate_review,
    evaluate_validation,
    plan_node,
)
from ant_orchestrator.workflows.routing import (
    RegroupDecision,
    RetryDecision,
    route_regroup,
    route_retry,
)
from ant_orchestrator.workflows.state import GraphState

__all__ = ["WORKFLOW_DEFINITION_VERSION", "build_workflow_graph"]

PHASE_PERSIST = "persist"
PHASE_COMPLETED = "completed"
PHASE_GATE_BLOCKED = "gate_blocked"

NODE_PLAN = "plan"
NODE_CONTEXT = "context"
NODE_DECISION = "decision"
NODE_EXECUTE = "execute_stub"
NODE_VALIDATE = "validate"
NODE_REVIEW = "review"
NODE_PERSIST = "persist_handoff"
NODE_FAILED = "failed"
NODE_GATE_BLOCKED = "gate_blocked"

_OUTCOME_KEY = "last_outcome"


def _as_int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) else default


def _status_of(delta: Mapping[str, object], key: str) -> str:
    result = delta.get(key)
    return str(result.get("status", "")) if isinstance(result, dict) else ""


def _intent_from_state(state: Mapping[str, object]) -> WorkerActionIntent:
    raw = state.get("action_intent")
    intent = raw if isinstance(raw, dict) else {}
    return WorkerActionIntent(
        logical_action_id=str(intent.get("logical_action_id") or f"{state.get('task_id', '')}-act"),
        summary=str(intent.get("summary") or "stub action"),
        requires_significant_write=bool(intent.get("requires_significant_write", False)),
        requires_unsafe_command=bool(intent.get("requires_unsafe_command", False)),
        target_paths=tuple(intent.get("target_paths") or ()),
        command_argv=tuple(intent.get("command_argv") or ()),
    )


def _intent_to_state(intent: WorkerActionIntent) -> dict[str, object]:
    return {
        "logical_action_id": intent.logical_action_id,
        "summary": intent.summary,
        "requires_significant_write": intent.requires_significant_write,
        "requires_unsafe_command": intent.requires_unsafe_command,
        "target_paths": list(intent.target_paths),
        "command_argv": list(intent.command_argv),
    }


def _route_after_validation(state: Mapping[str, object], status: str) -> dict[str, object]:
    if status == "pass":
        return {"phase": PHASE_REVIEW}
    if status == "retryable":
        route = route_retry(
            retry_count=_as_int(state.get("retry_count")),
            base_retry_limit=_as_int(state.get("base_retry_limit")),
            retry_extension_count=_as_int(state.get("retry_extension_count")),
        )
        if route.decision is RetryDecision.RETRY:
            return {"phase": PHASE_EXECUTE, "retry_count": route.retry_count}
        return {"phase": PHASE_GATE_BLOCKED}
    if status == "regroup":
        return _regroup_or_block(state)
    if status == "fatal":
        return {"phase": PHASE_FAILED}
    return {"phase": PHASE_GATE_BLOCKED}


def _route_after_review(state: Mapping[str, object], status: str) -> dict[str, object]:
    if status == "ok":
        return {"phase": PHASE_PERSIST}
    if status == "regroup":
        return _regroup_or_block(state)
    return {"phase": PHASE_GATE_BLOCKED}


def _regroup_or_block(state: Mapping[str, object]) -> dict[str, object]:
    route = route_regroup(regroup_count=_as_int(state.get("regroup_count")))
    if route.decision is RegroupDecision.REGROUP:
        return {"phase": PHASE_PLAN, "regroup_count": route.regroup_count}
    return {"phase": PHASE_GATE_BLOCKED}


def build_workflow_graph(worker: WorkerExecutionPort, policy: DecisionGatePolicy) -> StateGraph:
    """Build (but do not compile) the walking-skeleton graph over ``GraphState``."""

    def decision(state: GraphState) -> dict[str, object]:
        intent = _intent_from_state(state)
        if intent.requires_unsafe_command:
            result = policy.evaluate_unsafe_command(intent)
        else:
            result = policy.evaluate_significant_write(intent)
        delta = decision_node(state, result)
        delta["action_intent"] = _intent_to_state(intent)
        return delta

    def execute_stub(state: GraphState) -> dict[str, object]:
        intent = _intent_from_state(state)
        result = worker.execute(intent)
        action_intent = dict(state.get("action_intent") or {})
        action_intent[_OUTCOME_KEY] = result.outcome.value
        evidence = list(state.get("evidence_refs") or [])
        evidence.extend(result.evidence_refs)
        return {"action_intent": action_intent, "evidence_refs": evidence, "phase": PHASE_VALIDATE}

    def validate(state: GraphState) -> dict[str, object]:
        delta = dict(evaluate_validation(state, _last_outcome(state)))
        delta.update(_route_after_validation(state, _status_of(delta, "validation_result")))
        return delta

    def review(state: GraphState) -> dict[str, object]:
        delta = dict(evaluate_review(state, _last_outcome(state)))
        delta.update(_route_after_review(state, _status_of(delta, "review_result")))
        return delta

    graph = StateGraph(GraphState)
    graph.add_node(NODE_PLAN, plan_node)
    graph.add_node(NODE_CONTEXT, context_node)
    graph.add_node(NODE_DECISION, decision)
    graph.add_node(NODE_EXECUTE, execute_stub)
    graph.add_node(NODE_VALIDATE, validate)
    graph.add_node(NODE_REVIEW, review)
    graph.add_node(
        NODE_PERSIST, lambda state: {"final_outcome": "completed", "phase": PHASE_COMPLETED}
    )
    graph.add_node(NODE_FAILED, lambda state: {"final_outcome": "failed"})
    graph.add_node(NODE_GATE_BLOCKED, lambda state: {"final_outcome": "awaiting_approval"})

    graph.add_edge(START, NODE_PLAN)
    graph.add_edge(NODE_PLAN, NODE_CONTEXT)
    graph.add_edge(NODE_CONTEXT, NODE_DECISION)
    graph.add_conditional_edges(
        NODE_DECISION,
        _phase_of,
        {
            PHASE_EXECUTE: NODE_EXECUTE,
            PHASE_PREPARE_INTENT: NODE_GATE_BLOCKED,
            PHASE_FAILED: NODE_FAILED,
        },
    )
    graph.add_edge(NODE_EXECUTE, NODE_VALIDATE)
    graph.add_conditional_edges(
        NODE_VALIDATE,
        _phase_of,
        {
            PHASE_REVIEW: NODE_REVIEW,
            PHASE_EXECUTE: NODE_EXECUTE,
            PHASE_PLAN: NODE_PLAN,
            PHASE_FAILED: NODE_FAILED,
            PHASE_GATE_BLOCKED: NODE_GATE_BLOCKED,
        },
    )
    graph.add_conditional_edges(
        NODE_REVIEW,
        _phase_of,
        {
            PHASE_PERSIST: NODE_PERSIST,
            PHASE_PLAN: NODE_PLAN,
            PHASE_GATE_BLOCKED: NODE_GATE_BLOCKED,
        },
    )
    graph.add_edge(NODE_PERSIST, END)
    graph.add_edge(NODE_FAILED, END)
    graph.add_edge(NODE_GATE_BLOCKED, END)
    return graph


def _last_outcome(state: Mapping[str, object]) -> WorkerOutcome:
    action_intent = state.get("action_intent")
    value = action_intent.get(_OUTCOME_KEY) if isinstance(action_intent, dict) else None
    return WorkerOutcome(str(value))


def _phase_of(state: Mapping[str, object]) -> str:
    return str(state.get("phase", ""))
