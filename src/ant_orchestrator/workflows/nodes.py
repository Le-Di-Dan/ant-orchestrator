"""Pure workflow nodes (PHASE_4_PLAN C.12). Framework-neutral, no LangGraph node API.

Every function here is a *pure* transformation: it reads the (JSON-safe) graph state
and returns a delta dict. No node writes the DB, calls a repository/adapter, touches
the filesystem, runs a subprocess, reads the clock, or generates a random id. Nodes
never mutate the input state in place — they return a new fragment to be merged.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.workflows.decision_gate import DecisionGateOutcome, DecisionGateResult
from ant_orchestrator.workflows.intent import build_approval_intent

PHASE_PLAN: Final = "plan"
PHASE_CONTEXT: Final = "context"
PHASE_EXECUTE: Final = "execute"
PHASE_PREPARE_INTENT: Final = "prepare_intent"
PHASE_AWAIT_APPROVAL: Final = "await_approval"
PHASE_VALIDATE: Final = "validate"
PHASE_REVIEW: Final = "review"
PHASE_FAILED: Final = "failed"

_VALIDATION_STATUS: Final[Mapping[WorkerOutcome, str]] = {
    WorkerOutcome.SUCCESS: "pass",
    WorkerOutcome.RETRYABLE_FAILURE: "retryable",
    WorkerOutcome.VALIDATION_FAILURE: "retryable",
    WorkerOutcome.REVIEW_REGROUP: "regroup",
    WorkerOutcome.PERMANENT_FAILURE: "fatal",
    WorkerOutcome.ESCALATION: "escalate",
}

_REVIEW_STATUS: Final[Mapping[WorkerOutcome, str]] = {
    WorkerOutcome.SUCCESS: "ok",
    WorkerOutcome.REVIEW_REGROUP: "regroup",
    WorkerOutcome.ESCALATION: "escalate",
    WorkerOutcome.RETRYABLE_FAILURE: "escalate",
    WorkerOutcome.VALIDATION_FAILURE: "escalate",
    WorkerOutcome.PERMANENT_FAILURE: "escalate",
}

_DECISION_PHASE: Final[Mapping[DecisionGateOutcome, str]] = {
    DecisionGateOutcome.ALLOW: PHASE_EXECUTE,
    DecisionGateOutcome.REQUIRE_APPROVAL: PHASE_PREPARE_INTENT,
    DecisionGateOutcome.DENY: PHASE_FAILED,
}


def plan_node(state: Mapping[str, object]) -> dict[str, object]:
    """Produce a deterministic plan keyed to the task and the regroup revision."""
    revision = state.get("regroup_count", 0)
    task_id = state.get("task_id", "")
    return {
        "plan": {"goal": f"goal:{task_id}", "plan_revision": revision},
        "phase": PHASE_CONTEXT,
    }


def context_node(state: Mapping[str, object]) -> dict[str, object]:
    """Produce a deterministic context reference for the current plan revision."""
    run_id = state.get("workflow_run_id", "")
    plan = state.get("plan", {})
    revision = plan.get("plan_revision", 0) if isinstance(plan, dict) else 0
    return {"context_ref": f"ctx:{run_id}:{revision}", "phase": PHASE_EXECUTE}


def decision_node(state: Mapping[str, object], result: DecisionGateResult) -> dict[str, object]:
    """Record a gate decision as the next phase (and a sanitized reason on DENY)."""
    delta: dict[str, object] = {"phase": _DECISION_PHASE[result.outcome]}
    if result.outcome is DecisionGateOutcome.DENY:
        delta["error_summary"] = result.reason.value
    return delta


def _is_same_occurrence(
    existing: object, gate_type: GateType, logical_action_id: str, current_seq: int
) -> bool:
    return (
        isinstance(existing, dict)
        and existing.get("gate_type") == gate_type.value
        and existing.get("logical_action_id") == logical_action_id
        and existing.get("approval_gate_sequence") == current_seq
    )


def prepare_approval_intent(
    state: Mapping[str, object],
    *,
    gate_type: GateType,
    logical_action_id: str,
    payload: Mapping[str, object] | None = None,
    approved_continuation: ApprovalContinuation | None = None,
) -> dict[str, object]:
    """Build an ApprovalIntent for a new gate occurrence (replay reuses it).

    A new occurrence increments ``approval_gate_sequence`` by exactly one; replaying
    the same paused occurrence returns an empty delta (no increment, stable id).
    """
    current_seq = state.get("approval_gate_sequence", 0)
    if not isinstance(current_seq, int):
        current_seq = 0
    if _is_same_occurrence(state.get("approval_intent"), gate_type, logical_action_id, current_seq):
        return {}
    new_seq = current_seq + 1
    intent = build_approval_intent(
        workflow_run_id=str(state.get("workflow_run_id", "")),
        gate_type=gate_type,
        logical_action_id=logical_action_id,
        approval_gate_sequence=new_seq,
        payload=payload,
        approved_continuation=approved_continuation,
    )
    return {
        "approval_intent": intent.to_state_dict(),
        "approval_gate_sequence": new_seq,
        "phase": PHASE_AWAIT_APPROVAL,
    }


def evaluate_validation(state: Mapping[str, object], outcome: WorkerOutcome) -> dict[str, object]:
    """Map a worker outcome to a deterministic validation result."""
    return {
        "validation_result": {"status": _VALIDATION_STATUS[outcome], "reason_code": outcome.value},
        "phase": PHASE_VALIDATE,
    }


def evaluate_review(state: Mapping[str, object], outcome: WorkerOutcome) -> dict[str, object]:
    """Map a worker outcome to a deterministic review result."""
    return {
        "review_result": {"status": _REVIEW_STATUS[outcome], "reason_code": outcome.value},
        "phase": PHASE_REVIEW,
    }
