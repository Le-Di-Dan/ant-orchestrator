"""Workflow graph with the real human-approval interrupt path (PHASE_4_PLAN D.2).

LangGraph lives only in this module. CP4 adds node ``test`` (Test Ant execution) between
``execute_stub`` and ``validate``, a dedicated ``route_after_test_validation`` for the test
path, and bumps the definition version 3→4. Legacy graphs without a test port continue to
work: execute_stub routes to PHASE_VALIDATE and the test node is never entered.
"""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionPort,
)
from ant_orchestrator.application.ports.test_execution import (
    TestExecutionOutcome,
    TestExecutionPort,
)
from ant_orchestrator.application.ports.worker import WorkerExecutionPort, WorkerOutcome
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.cancellation_probe import CancellationProbe
from ant_orchestrator.workflows.decision_gate import DecisionGateOutcome, DecisionGatePolicy
from ant_orchestrator.workflows.energy_gate import evaluate_energy_gate
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
    PHASE_TEST,
    PHASE_VALIDATE,
    apply_approval_delta,
    bind_approval,
    build_escalation_payload,
    execute_documentation_node,
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
from ant_orchestrator.workflows.test_routing import route_after_test_validation

__all__ = ["WORKFLOW_DEFINITION_VERSION", "build_workflow_graph"]

NODE_PLAN = "plan"
NODE_CONTEXT = "context"
NODE_DECISION = "decision"
NODE_EXECUTE = "execute_stub"
NODE_TEST = "test"
NODE_VALIDATE = "validate"
NODE_REVIEW = "review"
NODE_PREPARE_INTENT = "prepare_intent"
NODE_AWAIT_APPROVAL = "await_approval"
NODE_PERSIST = "persist_handoff"
NODE_FAILED = "failed"
NODE_REJECTED = "rejected"
NODE_CANCELLED = "cancelled"


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


# Compact test outcome → routing status for node ``test``.
_TEST_STATUS: dict[WorkerOutcome, str] = {
    WorkerOutcome.SUCCESS: "pass",
    WorkerOutcome.RETRYABLE_FAILURE: "retryable",
    WorkerOutcome.ESCALATION: "escalate",
    WorkerOutcome.PERMANENT_FAILURE: "fatal",
}


def _execute_test_port(
    port: TestExecutionPort, state: GraphState, run_id: str
) -> dict[str, object]:
    """Call the TestExecutionPort and fold its compact outcome into graph state.

    No classifier logic, no retry policy, no Docker — only the impure call and state
    delta. Cancellation (TERMINAL_CANCELLED disposition) routes directly to CANCELLED.
    """
    outcome: TestExecutionOutcome = port.execute(
        task_id=str(state.get("task_id", "")),
        run_id=run_id,
        context_manifest_digest=str(state.get("manifest_digest") or ""),
    )
    if outcome.is_cancelled:
        return {"phase": PHASE_CANCELLED}
    delta: dict[str, object] = {
        "phase": PHASE_VALIDATE,
        "test_status": _TEST_STATUS.get(outcome.outcome, "escalate"),
        "test_outcome": outcome.outcome.value,
        "test_attempt_ref": outcome.attempt_ref,
        "test_logical_action_ref": outcome.attempt_ref,  # stable action bound to attempt
    }
    if outcome.category is not None:
        delta["test_failure_category"] = outcome.category.value
    if outcome.reason_code is not None:
        delta["test_reason_code"] = outcome.reason_code.value
    if outcome.disposition is not None:
        delta["test_recovery_disposition"] = outcome.disposition.value
    if outcome.evidence_refs:
        delta["test_evidence_refs"] = list(outcome.evidence_refs)
    return delta


def build_workflow_graph(
    worker: WorkerExecutionPort,
    policy: DecisionGatePolicy,
    attempt_orchestrator: AttemptOrchestrator | None = None,
    cancellation_probe: CancellationProbe | None = None,
    documentation_execution: DocumentationExecutionPort | None = None,
    test_execution: TestExecutionPort | None = None,
) -> StateGraph:
    """Build (but do not compile) the graph.

    ``documentation_execution``: Phase 5 durable Documentation Ant (fail-closed when None
    in production). ``test_execution``: Phase 6 durable Test Ant — when set, execute_stub
    routes to node ``test`` before ``validate``; when None (legacy/unit tests), the graph
    skips the test node and routes directly to ``validate``.
    """

    def decision(state: GraphState) -> dict[str, object]:
        intent = intent_from_state(state)
        if intent.requires_energy_approval:
            result = evaluate_energy_gate(policy, str(state.get("task_id", "")))
        elif intent.requires_unsafe_command:
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
        run_id = str(state.get("workflow_run_id", ""))
        if cancellation_probe is not None and cancellation_probe.is_cancel_requested(run_id):
            return {"phase": PHASE_CANCELLED}
        # Phase 6 production: Documentation Ant then Test Ant.
        next_phase = PHASE_TEST if test_execution is not None else PHASE_VALIDATE
        if documentation_execution is not None:
            return execute_documentation_node(
                documentation_execution, state, run_id, next_phase=next_phase
            )
        # Legacy stub worker (tests / pre-Phase-5 path).
        intent = intent_from_state(state)
        attempt_id: str | None = None
        if attempt_orchestrator is not None:
            attempt_id = attempt_orchestrator.before_execute(run_id, intent.logical_action_id)
        result = worker.execute(intent)
        if attempt_orchestrator is not None and attempt_id is not None:
            attempt_orchestrator.after_execute(attempt_id, result.outcome)
        action_intent = dict(state.get("action_intent") or {})
        action_intent["last_outcome"] = result.outcome.value
        evidence = list(state.get("evidence_refs") or [])
        evidence.extend(result.evidence_refs)
        return {
            "action_intent": action_intent,
            "evidence_refs": evidence,
            "phase": next_phase,
            "execution_attempt_ref": attempt_id,
        }

    def test(state: GraphState) -> dict[str, object]:
        """Impure Test Ant boundary — check cancel, call port, write compact state delta."""
        run_id = str(state.get("workflow_run_id", ""))
        if cancellation_probe is not None and cancellation_probe.is_cancel_requested(run_id):
            return {"phase": PHASE_CANCELLED}
        if test_execution is None:
            # Legacy mode: no test port injected → deterministic pass-through.
            return {"phase": PHASE_VALIDATE, "test_status": "pass"}
        return _execute_test_port(test_execution, state, run_id)

    def validate(state: GraphState) -> dict[str, object]:
        test_status = state.get("test_status")
        if test_status is not None:
            # Test Ant path: compact outcome already set by node ``test``.
            route = route_after_test_validation(state, str(test_status))
            delta: dict[str, object] = {}
            _apply_route(delta, state, route)
            return delta
        # Legacy DocAnt path (unchanged behavior).
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
        delta["approval_intent"] = None
        bind_approval(delta, intent, state)
        return delta

    graph = StateGraph(GraphState)
    graph.add_node(NODE_PLAN, plan_node)
    graph.add_node(NODE_CONTEXT, context_node)
    graph.add_node(NODE_DECISION, decision)
    graph.add_node(NODE_EXECUTE, execute_stub)
    graph.add_node(NODE_TEST, test)
    graph.add_node(NODE_VALIDATE, validate)
    graph.add_node(NODE_REVIEW, review)
    graph.add_node(NODE_PREPARE_INTENT, prepare_intent)
    graph.add_node(NODE_AWAIT_APPROVAL, await_approval)

    def persist_handoff(state: GraphState) -> dict[str, object]:
        run_id = str(state.get("workflow_run_id", ""))
        if cancellation_probe is not None and cancellation_probe.is_cancel_requested(run_id):
            return {"phase": PHASE_CANCELLED}
        return {"final_outcome": "completed", "phase": PHASE_COMPLETED}

    graph.add_node(NODE_PERSIST, persist_handoff)
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
            PHASE_FAILED: NODE_FAILED,
        },
    )
    graph.add_conditional_edges(
        NODE_EXECUTE,
        phase_of,
        {
            PHASE_VALIDATE: NODE_VALIDATE,  # legacy path (no test port)
            PHASE_TEST: NODE_TEST,  # Phase 6 path (test port injected)
            PHASE_CANCELLED: NODE_CANCELLED,
            PHASE_FAILED: NODE_FAILED,
        },
    )
    graph.add_conditional_edges(
        NODE_TEST,
        phase_of,
        {
            PHASE_VALIDATE: NODE_VALIDATE,
            PHASE_CANCELLED: NODE_CANCELLED,
        },
    )
    graph.add_conditional_edges(
        NODE_VALIDATE,
        phase_of,
        {
            PHASE_REVIEW: NODE_REVIEW,
            PHASE_TEST: NODE_TEST,  # Test Ant retry (CP4)
            PHASE_EXECUTE: NODE_EXECUTE,  # DocAnt retry (legacy)
            PHASE_PLAN: NODE_PLAN,
            PHASE_FAILED: NODE_FAILED,
            PHASE_PREPARE_INTENT: NODE_PREPARE_INTENT,
            PHASE_CANCELLED: NODE_CANCELLED,
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
    graph.add_conditional_edges(
        NODE_PERSIST,
        phase_of,
        {PHASE_COMPLETED: END, PHASE_CANCELLED: NODE_CANCELLED},
    )
    graph.add_edge(NODE_FAILED, END)
    graph.add_edge(NODE_REJECTED, END)
    graph.add_edge(NODE_CANCELLED, END)
