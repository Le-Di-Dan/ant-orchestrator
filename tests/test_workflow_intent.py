"""ApprovalIntent + deterministic gate-instance id tests (CP2)."""

from __future__ import annotations

import hashlib

import pytest

from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.workflows.intent import (
    build_approval_intent,
    canonical_gate_key,
    compute_gate_instance_id,
    continuation_for_gate,
    review_escalation_continuation,
)
from ant_orchestrator.workflows.state import GraphStateError


def test_gate_id_is_deterministic() -> None:
    a = compute_gate_instance_id("R1", GateType.RETRY_LIMIT, "act-1", 1)
    b = compute_gate_instance_id("R1", GateType.RETRY_LIMIT, "act-1", 1)
    assert a == b


def test_gate_id_changes_with_sequence_gate_and_action() -> None:
    base = compute_gate_instance_id("R1", GateType.RETRY_LIMIT, "act-1", 1)
    assert base != compute_gate_instance_id("R1", GateType.RETRY_LIMIT, "act-1", 2)
    assert base != compute_gate_instance_id("R1", GateType.ENERGY_BUDGET, "act-1", 1)
    assert base != compute_gate_instance_id("R1", GateType.RETRY_LIMIT, "act-2", 1)
    assert base != compute_gate_instance_id("R2", GateType.RETRY_LIMIT, "act-1", 1)


def test_gate_id_matches_stable_vector() -> None:
    # Pins the algorithm: gate-<sha256(canonical_key)>. Reconstructed independently.
    key = canonical_gate_key("R1", GateType.SIGNIFICANT_WRITE, "act-1", 3)
    expected = "gate-" + hashlib.sha256(key.encode("utf-8")).hexdigest()
    assert compute_gate_instance_id("R1", GateType.SIGNIFICANT_WRITE, "act-1", 3) == expected
    assert key == "R1\x1fsignificant_write\x1fact-1\x1f3"


def test_continuation_for_each_gate() -> None:
    assert continuation_for_gate(GateType.SIGNIFICANT_WRITE) is ApprovalContinuation.EXECUTE
    assert continuation_for_gate(GateType.UNSAFE_COMMAND) is ApprovalContinuation.EXECUTE
    assert continuation_for_gate(GateType.ENERGY_BUDGET) is ApprovalContinuation.EXECUTE
    assert continuation_for_gate(GateType.RETRY_LIMIT) is ApprovalContinuation.EXECUTE
    assert continuation_for_gate(GateType.SCOPE_CHANGE) is ApprovalContinuation.REPLAN


def test_review_escalation_allows_accept_or_replan_only() -> None:
    assert review_escalation_continuation(ApprovalContinuation.ACCEPT_RESULT)
    assert review_escalation_continuation(ApprovalContinuation.REPLAN)
    with pytest.raises(InvariantViolation):
        review_escalation_continuation(ApprovalContinuation.EXECUTE)


def test_build_intent_sanitizes_payload_and_has_no_rejected_continuation() -> None:
    intent = build_approval_intent(
        workflow_run_id="R1",
        gate_type=GateType.SCOPE_CHANGE,
        logical_action_id="act-1",
        approval_gate_sequence=1,
        payload={"reason": "scope grew", "count": 3},
    )
    assert intent.approved_continuation is ApprovalContinuation.REPLAN
    state_dict = intent.to_state_dict()
    assert state_dict["sanitized_payload"] == {"reason": "scope grew", "count": 3}
    assert "rejected_continuation" not in state_dict
    # Only JSON-safe primitives end up in the state dict (gate_type rendered to value).
    assert state_dict["gate_type"] == "scope_change"


def test_build_intent_rejects_non_json_payload() -> None:
    with pytest.raises(GraphStateError):
        build_approval_intent(
            workflow_run_id="R1",
            gate_type=GateType.ENERGY_BUDGET,
            logical_action_id="act-1",
            approval_gate_sequence=1,
            payload={"secret": object()},
        )


def test_intent_carries_no_concrete_node_name() -> None:
    intent = build_approval_intent(
        workflow_run_id="R1",
        gate_type=GateType.SIGNIFICANT_WRITE,
        logical_action_id="act-1",
        approval_gate_sequence=1,
    )
    rendered = str(intent.to_state_dict())
    for node_name in ("execute_stub", "persist_handoff"):
        assert node_name not in rendered
