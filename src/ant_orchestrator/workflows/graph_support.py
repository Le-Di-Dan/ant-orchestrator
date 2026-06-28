"""Framework-free helpers for the workflow graph (PHASE_4_PLAN D.2/D.4).

These functions are pure: they read the JSON-safe graph state and return small
delta dicts. They never import LangGraph, so the routing logic stays testable and
the concrete node names live only in ``graph.py``. The escalation routes carry the
``gate_type``/``continuation`` of the gate that must be raised, so the graph can fold
them into a single ``prepare_intent`` → ``await_approval`` interrupt path.
"""

from __future__ import annotations

from collections.abc import Mapping

from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionOutcome,
    DocumentationExecutionPort,
)
from ant_orchestrator.application.ports.worker import WorkerActionIntent, WorkerOutcome
from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.workflows.routing import (
    GrantDecision,
    RegroupDecision,
    RetryDecision,
    effective_retry_limit,
    grant_retry_extension,
    route_regroup,
    route_retry,
)
from ant_orchestrator.workflows.state import GraphState

# Phase markers used by the conditional edges.
PHASE_PLAN = "plan"
PHASE_EXECUTE = "execute"
PHASE_TEST = "test"  # CP4: dedicated Test Ant execution node
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


def build_escalation_payload(
    state: Mapping[str, object], gate_type: GateType, reason: str
) -> dict[str, object]:
    """Build a sanitized payload with diagnostic counters for an escalation gate.

    For a Phase 5 documentation write, the proposal binding (ref/digest/target) is folded
    in so the human reviews — and the approval binds — the exact proposal that will run.
    """
    payload: dict[str, object] = {"reason": reason}
    if gate_type is GateType.RETRY_LIMIT:
        payload["retry_count"] = as_int(state.get("retry_count"))
        payload["effective_retry_limit"] = effective_retry_limit(
            as_int(state.get("base_retry_limit")),
            as_int(state.get("retry_extension_count")),
        )
    elif gate_type is GateType.SCOPE_CHANGE:
        payload["regroup_count"] = as_int(state.get("regroup_count"))
    proposal_digest = state.get("proposal_digest")
    if isinstance(proposal_digest, str) and proposal_digest:
        payload["proposal_ref"] = str(state.get("proposal_ref", ""))
        payload["proposal_digest"] = proposal_digest
        payload["manifest_digest"] = str(state.get("manifest_digest", ""))
    return payload


def apply_approval_delta(
    intent: Mapping[str, object],
    decision: str,
    state: Mapping[str, object],
) -> dict[str, object]:
    """Full delta after an approval decision: phase + RetryGrant when RETRY_LIMIT approved.

    REJECT/CANCEL route to fixed terminal phases. APPROVE follows the continuation
    from the intent; a RETRY_LIMIT approval triggers a one-time extension grant
    (fail-closed if the MAX_RETRY_EXTENSIONS bound is already reached).
    """
    if decision == RESUME_REJECTED:
        return {"phase": PHASE_REJECTED}
    if decision == RESUME_CANCELLED:
        return {"phase": PHASE_CANCELLED}
    continuation = ApprovalContinuation(str(intent.get("approved_continuation")))
    delta: dict[str, object] = {"phase": _CONTINUATION_PHASE[continuation]}
    if (
        intent.get("gate_type") == GateType.RETRY_LIMIT.value
        and continuation is ApprovalContinuation.EXECUTE
    ):
        result = grant_retry_extension(
            retry_extension_count=as_int(state.get("retry_extension_count"))
        )
        if result.decision is GrantDecision.GRANTED:
            delta["retry_extension_count"] = result.retry_extension_count
        else:
            delta["phase"] = PHASE_FAILED
    return delta


def _regroup_or_escalate(state: Mapping[str, object]) -> dict[str, object]:
    route = route_regroup(regroup_count=as_int(state.get("regroup_count")))
    if route.decision is RegroupDecision.REGROUP:
        return {"phase": PHASE_PLAN, "regroup_count": route.regroup_count}
    return _escalate(GateType.SCOPE_CHANGE, ApprovalContinuation.REPLAN)


def _escalate(gate_type: GateType, continuation: ApprovalContinuation) -> dict[str, object]:
    return {"phase": PHASE_PREPARE_INTENT, "gate_type": gate_type, "continuation": continuation}


# ---------------------------------------------------------------------------
# Helpers moved here from graph.py (CP4) to keep graph.py under 350 lines.
# ---------------------------------------------------------------------------

_DOC_OUTCOME_KEY = "last_outcome"


def bind_approval(delta: dict[str, object], intent: dict[str, object], state: GraphState) -> None:
    """On approve-to-execute, verify the approval binds this proposal and stamp its ref.

    A mismatch with the durable proposal in state means the approval is for a different
    proposal — fail closed (no execution under a foreign authority).
    """
    if delta.get("phase") != PHASE_EXECUTE:
        return
    proposal_digest = state.get("proposal_digest")
    if not (isinstance(proposal_digest, str) and proposal_digest):
        return
    payload = intent.get("sanitized_payload")
    bound = payload.get("proposal_digest") if isinstance(payload, dict) else None
    if bound != proposal_digest:
        delta["phase"] = PHASE_FAILED
        delta["error_summary"] = "approval_binding_mismatch"
        return
    delta["approval_ref"] = str(intent.get("gate_instance_id", ""))


def execute_documentation_node(
    port: DocumentationExecutionPort,
    state: GraphState,
    run_id: str,
    next_phase: str = PHASE_VALIDATE,
) -> dict[str, object]:
    """Drive the durable Documentation Ant path; fail closed on missing proposal authority.

    ``next_phase`` controls where the graph routes after a successful execution:
    ``PHASE_VALIDATE`` (legacy) or ``PHASE_TEST`` (Phase 6, when Test Ant follows).
    """
    proposal_ref = str(state.get("proposal_ref", ""))
    proposal_digest = str(state.get("proposal_digest", ""))
    if not proposal_ref or not proposal_digest:
        return {"phase": PHASE_FAILED, "error_summary": "missing_proposal_authority"}
    outcome: DocumentationExecutionOutcome = port.execute(
        task_id=str(state.get("task_id", "")),
        run_id=run_id,
        proposal_ref=proposal_ref,
        proposal_digest=proposal_digest,
        approval_ref=str(state.get("approval_ref", "")),
    )
    action_intent = dict(state.get("action_intent") or {})
    action_intent[_DOC_OUTCOME_KEY] = outcome.outcome.value
    evidence = list(state.get("evidence_refs") or [])
    evidence.extend(outcome.evidence_refs)
    return {
        "action_intent": action_intent,
        "evidence_refs": evidence,
        "phase": next_phase,
        "execution_attempt_ref": outcome.attempt_ref,
    }
