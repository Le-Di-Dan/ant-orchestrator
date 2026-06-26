"""Framework-free helpers for the workflow graph (PHASE_4_PLAN D.2/D.4).

These functions are pure: they read the JSON-safe graph state and return small
delta dicts. They never import LangGraph, so the routing logic stays testable and
the concrete node names live only in ``graph.py``. The escalation routes carry the
``gate_type``/``continuation`` of the gate that must be raised, so the graph can fold
them into a single ``prepare_intent`` → ``await_approval`` interrupt path.
"""

from __future__ import annotations

from collections.abc import Mapping

from ant_orchestrator.application.ports.worker import WorkerActionIntent, WorkerOutcome
from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.workflows.routing import (
    RegroupDecision,
    RetryDecision,
    route_regroup,
    route_retry,
)

# Phase markers used by the conditional edges.
PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_PREPARE_INTENT = "prepare_intent"
PHASE_AWAIT_APPROVAL = "await_approval"
PHASE_VALIDATE = "validate"
PHASE_REVIEW = "review"
PHASE_PERSIST = "persist"
PHASE_COMPLETED = "completed"
PHASE_FAILED = "failed"
PHASE_REJECTED = "rejected"
PHASE_CANCELLED = "cancelled"

# Resume decision tokens carried through ``Command(resume=...)`` (ApprovalStatus values).
RESUME_APPROVED = "approved"
RESUME_REJECTED = "rejected"
RESUME_CANCELLED = "cancelled"

_OUTCOME_KEY = "last_outcome"
# action_intent keys describing the gate that must be raised next (set by routing).
_PENDING_GATE_TYPE = "pending_gate_type"
_PENDING_CONTINUATION = "pending_continuation"
_PENDING_REASON = "pending_reason"

_CONTINUATION_PHASE: Mapping[ApprovalContinuation, str] = {
    ApprovalContinuation.EXECUTE: PHASE_EXECUTE,
    ApprovalContinuation.REPLAN: PHASE_PLAN,
    ApprovalContinuation.ACCEPT_RESULT: PHASE_PERSIST,
}


def as_int(value: object, default: int = 0) -> int:
    """Coerce a JSON-safe value to int (LangGraph stores ints as ints)."""
    return value if isinstance(value, int) else default


def phase_of(state: Mapping[str, object]) -> str:
    """Return the routing phase recorded by the last node."""
    return str(state.get("phase", ""))


def status_of(delta: Mapping[str, object], key: str) -> str:
    """Read the ``status`` of a nested validation/review result dict."""
    result = delta.get(key)
    return str(result.get("status", "")) if isinstance(result, dict) else ""


def last_outcome(state: Mapping[str, object]) -> WorkerOutcome:
    """Recover the worker outcome that ``execute_stub`` recorded into action_intent."""
    action_intent = state.get("action_intent")
    value = action_intent.get(_OUTCOME_KEY) if isinstance(action_intent, dict) else None
    return WorkerOutcome(str(value))


def intent_from_state(state: Mapping[str, object]) -> WorkerActionIntent:
    """Build a structured worker intent from the JSON-safe action_intent dict."""
    raw = state.get("action_intent")
    intent = raw if isinstance(raw, dict) else {}
    return WorkerActionIntent.from_state_dict(intent, default_id=f"{state.get('task_id', '')}-act")


def intent_to_state(intent: WorkerActionIntent) -> dict[str, object]:
    """Render a worker intent back into a JSON-safe dict for graph state."""
    return intent.to_state_dict()


def mark_pending_gate(
    action_intent: dict[str, object],
    *,
    gate_type: GateType,
    continuation: ApprovalContinuation | None,
    reason: str,
) -> None:
    """Record the gate the next ``prepare_intent`` node must raise."""
    action_intent[_PENDING_GATE_TYPE] = gate_type.value
    action_intent[_PENDING_CONTINUATION] = continuation.value if continuation is not None else None
    action_intent[_PENDING_REASON] = reason


def read_pending_gate(
    action_intent: Mapping[str, object],
) -> tuple[GateType, ApprovalContinuation | None, str]:
    """Read the pending-gate fields back as typed values for ``prepare_intent``."""
    gate_type = GateType(str(action_intent.get(_PENDING_GATE_TYPE)))
    cont_raw = action_intent.get(_PENDING_CONTINUATION)
    continuation = ApprovalContinuation(str(cont_raw)) if cont_raw else None
    reason = str(action_intent.get(_PENDING_REASON) or "")
    return gate_type, continuation, reason


def route_after_validation(state: Mapping[str, object], status: str) -> dict[str, object]:
    """Map a validation status to the next phase (escalations name their gate)."""
    if status == "pass":
        return {"phase": PHASE_REVIEW}
    if status == "retryable":
        route = route_retry(
            retry_count=as_int(state.get("retry_count")),
            base_retry_limit=as_int(state.get("base_retry_limit")),
            retry_extension_count=as_int(state.get("retry_extension_count")),
        )
        if route.decision is RetryDecision.RETRY:
            return {"phase": PHASE_EXECUTE, "retry_count": route.retry_count}
        return _escalate(GateType.RETRY_LIMIT, ApprovalContinuation.EXECUTE)
    if status == "regroup":
        return _regroup_or_escalate(state)
    if status == "fatal":
        return {"phase": PHASE_FAILED}
    return _escalate(GateType.SCOPE_CHANGE, ApprovalContinuation.REPLAN)


def route_after_review(state: Mapping[str, object], status: str) -> dict[str, object]:
    """Map a review status to the next phase (escalation raises SCOPE_CHANGE)."""
    if status == "ok":
        return {"phase": PHASE_PERSIST}
    if status == "regroup":
        return _regroup_or_escalate(state)
    return _escalate(GateType.SCOPE_CHANGE, ApprovalContinuation.REPLAN)


def route_after_approval(intent: Mapping[str, object], decision: str) -> str:
    """Map a resume decision to a phase (APPROVE follows the approved continuation)."""
    if decision == RESUME_REJECTED:
        return PHASE_REJECTED
    if decision == RESUME_CANCELLED:
        return PHASE_CANCELLED
    continuation = ApprovalContinuation(str(intent.get("approved_continuation")))
    return _CONTINUATION_PHASE[continuation]


def _regroup_or_escalate(state: Mapping[str, object]) -> dict[str, object]:
    route = route_regroup(regroup_count=as_int(state.get("regroup_count")))
    if route.decision is RegroupDecision.REGROUP:
        return {"phase": PHASE_PLAN, "regroup_count": route.regroup_count}
    return _escalate(GateType.SCOPE_CHANGE, ApprovalContinuation.REPLAN)


def _escalate(gate_type: GateType, continuation: ApprovalContinuation) -> dict[str, object]:
    return {"phase": PHASE_PREPARE_INTENT, "gate_type": gate_type, "continuation": continuation}
