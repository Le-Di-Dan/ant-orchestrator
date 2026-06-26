"""ApprovalIntent contract + deterministic gate-instance identity (PHASE_4_PLAN C.5/C.6).

Framework-neutral and sanitized. ``gate_instance_id`` is a deterministic hash of
``(workflow_run_id, gate_type, logical_action_id, approval_gate_sequence)`` — never a
random UUID and never Python's ``hash()`` (which is not stable across processes).
There is no ``rejected_continuation``: REJECT/CANCEL are fixed terminal routes
applied by the orchestration phase, so only APPROVE carries a continuation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass

from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.workflows.state import sanitize_payload

# Unit-separator joins the identity tuple; it cannot occur in normal identifiers.
_KEY_SEP = "\x1f"
_GATE_ID_PREFIX = "gate-"

_CONTINUATION_BY_GATE: Mapping[GateType, ApprovalContinuation] = {
    GateType.SIGNIFICANT_WRITE: ApprovalContinuation.EXECUTE,
    GateType.UNSAFE_COMMAND: ApprovalContinuation.EXECUTE,
    GateType.ENERGY_BUDGET: ApprovalContinuation.EXECUTE,
    GateType.RETRY_LIMIT: ApprovalContinuation.EXECUTE,
    GateType.SCOPE_CHANGE: ApprovalContinuation.REPLAN,
}

# A review escalation lets the caller accept the result or replan (no EXECUTE).
_REVIEW_ESCALATION_CHOICES = frozenset(
    {ApprovalContinuation.ACCEPT_RESULT, ApprovalContinuation.REPLAN}
)


def canonical_gate_key(
    workflow_run_id: str,
    gate_type: GateType,
    logical_action_id: str,
    approval_gate_sequence: int,
) -> str:
    """Build the stable canonical identity string (the hash pre-image)."""
    return _KEY_SEP.join(
        (workflow_run_id, gate_type.value, logical_action_id, str(approval_gate_sequence))
    )


def compute_gate_instance_id(
    workflow_run_id: str,
    gate_type: GateType,
    logical_action_id: str,
    approval_gate_sequence: int,
) -> str:
    """Deterministic ``gate-<sha256>`` id for one gate occurrence (stable across runs)."""
    key = canonical_gate_key(workflow_run_id, gate_type, logical_action_id, approval_gate_sequence)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{_GATE_ID_PREFIX}{digest}"


def continuation_for_gate(gate_type: GateType) -> ApprovalContinuation:
    """Return the fixed approve-continuation for a standard gate type."""
    try:
        return _CONTINUATION_BY_GATE[gate_type]
    except KeyError as exc:
        raise InvariantViolation(f"no continuation mapping for gate {gate_type}") from exc


def review_escalation_continuation(choice: ApprovalContinuation) -> ApprovalContinuation:
    """Validate a caller's review-escalation choice (ACCEPT_RESULT or REPLAN)."""
    if choice not in _REVIEW_ESCALATION_CHOICES:
        raise InvariantViolation(f"invalid review-escalation continuation: {choice}")
    return choice


@dataclass(frozen=True, slots=True)
class ApprovalIntent:
    """A sanitized, framework-neutral description of one approval gate occurrence."""

    gate_instance_id: str
    gate_type: GateType
    logical_action_id: str
    approval_gate_sequence: int
    approved_continuation: ApprovalContinuation
    sanitized_payload: Mapping[str, object]

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict for inclusion in graph state (enums → values)."""
        return {
            "gate_instance_id": self.gate_instance_id,
            "gate_type": self.gate_type.value,
            "logical_action_id": self.logical_action_id,
            "approval_gate_sequence": self.approval_gate_sequence,
            "approved_continuation": self.approved_continuation.value,
            "sanitized_payload": dict(self.sanitized_payload),
        }


def build_approval_intent(
    *,
    workflow_run_id: str,
    gate_type: GateType,
    logical_action_id: str,
    approval_gate_sequence: int,
    payload: Mapping[str, object] | None = None,
    approved_continuation: ApprovalContinuation | None = None,
) -> ApprovalIntent:
    """Construct an ApprovalIntent with a deterministic gate id and sanitized payload.

    ``approved_continuation`` defaults to the gate's fixed mapping; a review
    escalation may override it with ACCEPT_RESULT/REPLAN (validated).
    """
    if approved_continuation is None:
        continuation = continuation_for_gate(gate_type)
    else:
        continuation = approved_continuation
    gate_instance_id = compute_gate_instance_id(
        workflow_run_id, gate_type, logical_action_id, approval_gate_sequence
    )
    sanitized = sanitize_payload(payload) if payload is not None else {}
    return ApprovalIntent(
        gate_instance_id=gate_instance_id,
        gate_type=gate_type,
        logical_action_id=logical_action_id,
        approval_gate_sequence=approval_gate_sequence,
        approved_continuation=continuation,
        sanitized_payload=sanitized,
    )
