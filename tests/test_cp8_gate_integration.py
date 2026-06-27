"""CP8 — Scenario F: escalation + gate integration across processes (subprocess).

Demonstrates each gate type reaching a durable pending approval *before any worker
runs*: SIGNIFICANT_WRITE and UNSAFE_COMMAND via the real decision node, ENERGY_BUDGET
via the real Phase 3 ``EnforcementPolicy`` (no parallel policy). RETRY_LIMIT and
SCOPE_CHANGE are covered in ``test_cp8_retry_regroup``. The structured-intent gates
run the scripted worker with an *empty* script, so any premature worker invocation
would raise ``StubScriptExhausted`` instead of pausing — that is the no-side-effect
proof.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import cli_approve, driver, expect_ok, init_and_create

# Keys that must never leak into a sanitized approval payload.
_SECRET_MARKERS = ("secret", "token", "password", "api_key", "request_json")


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


def _assert_pending_gate_no_side_effects(workspace: Path, *, gate_type: str) -> None:
    """A single durable pending approval of ``gate_type`` with no worker activity."""
    approvals = ev.approvals(workspace)
    assert len(approvals) == 1
    assert approvals[0]["status"] == "pending"
    assert approvals[0]["gate_type"] == gate_type
    assert approvals[0]["langgraph_interrupt_id"]  # durable interrupt
    assert approvals[0]["langgraph_checkpoint_id"]  # durable checkpoint
    # Zero worker invocation / zero active ExecutionAttempt before approval.
    assert ev.count_rows(workspace, "execution_attempts") == 0
    # Payload is sanitized: valid JSON, no secret-bearing markers.
    raw = approvals[0]["request_json"]
    assert isinstance(raw, str)
    payload = json.loads(raw)  # parses cleanly
    assert isinstance(payload, dict)
    lowered = raw.lower()
    assert not any(marker in lowered for marker in _SECRET_MARKERS)


# ---------------------------------------------------------------------------
# SIGNIFICANT_WRITE — structured intent → checkpoint → pending → no worker
# ---------------------------------------------------------------------------


def test_significant_write_gate_pauses_before_worker(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    paused = expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )
    assert paused["status"] == "waiting_for_approval"
    _assert_pending_gate_no_side_effects(workspace, gate_type="significant_write")

    # Only after approval does execution proceed (one attempt, then completion).
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    assert ev.succeeded_attempt_count(workspace) == 1


# ---------------------------------------------------------------------------
# UNSAFE_COMMAND — structured intent → checkpoint → pending → no worker
# ---------------------------------------------------------------------------


def test_unsafe_command_gate_pauses_before_worker(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    paused = expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--unsafe-command"])
    )
    assert paused["status"] == "waiting_for_approval"
    _assert_pending_gate_no_side_effects(workspace, gate_type="unsafe_command")

    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    assert ev.succeeded_attempt_count(workspace) == 1


# ---------------------------------------------------------------------------
# ENERGY_BUDGET — structured intent → real EnforcementPolicy → durable interrupt
# ---------------------------------------------------------------------------


def test_energy_budget_gate_pauses_before_worker(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    # The decision node routes an energy-governed action through the same Phase 3
    # EnforcementPolicy; with no covered budget it requires approval and interrupts.
    paused = expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--energy-approval"])
    )
    assert paused["status"] == "waiting_for_approval"
    _assert_pending_gate_no_side_effects(workspace, gate_type="energy_budget")

    # After approval the locked EXECUTE continuation runs exactly one attempt.
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    assert ev.succeeded_attempt_count(workspace) == 1


def test_energy_budget_policy_mapping(tmp_path: Path) -> None:
    # Direct cross-process check that the Phase 3 EnforcementPolicy is the one used.
    result = expect_ok("energy-gate", driver("energy-gate", tmp_path))
    assert result["gate_type"] == "energy_budget"
    assert result["outcome"] == "require_approval"
    assert result["reason"] == "energy_requires_approval"
