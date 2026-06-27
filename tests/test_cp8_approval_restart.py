"""CP8 — Scenarios A/B/C: pause in one process, resolve in a fresh process.

Process A is the test-only driver (it forces a SIGNIFICANT_WRITE gate the vanilla
production stub cannot reach); it pauses durably and exits. Process B is the *public*
``ant`` CLI, which re-opens the state DB and checkpointer from disk and resolves the
gate. All evidence is read back through fresh connections / a fresh checkpointer.
"""

from __future__ import annotations

from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import (
    cli_approve,
    cli_cancel,
    cli_reject,
    driver,
    expect_ok,
    init_and_create,
)


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


def _pause(workspace: Path, task_id: str) -> dict[str, object]:
    """Process A: drive the task to AWAITING_APPROVAL and exit. Returns the payload."""
    payload = expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )
    assert payload["status"] == "waiting_for_approval"
    return payload


# ---------------------------------------------------------------------------
# Scenario A — pause, restart, approve, resume-not-rerun
# ---------------------------------------------------------------------------


def test_scenario_a_pause_restart_approve_resume_not_rerun(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    # --- Process A: durable pause ---
    paused = _pause(workspace, task_id)
    run_id = str(paused["workflow_run_id"])
    approval_id = str(paused["approval_id"])

    assert ev.task_status(workspace, task_id) == "waiting_for_approval"
    assert ev.run_status(workspace, run_id) == "awaiting_approval"
    pending = ev.approvals(workspace)
    assert len(pending) == 1
    assert pending[0]["id"] == approval_id
    assert pending[0]["status"] == "pending"
    assert pending[0]["langgraph_interrupt_id"]  # interrupt id persisted
    assert pending[0]["langgraph_checkpoint_id"]  # checkpoint id persisted
    thread_id = ev.run_row(workspace, run_id)["thread_id"]
    counts_before = ev.node_schedule_counts(workspace, run_id)
    assert counts_before.get("plan") == 1
    assert counts_before.get("context") == 1
    assert ev.count_rows(workspace, "execution_attempts") == 0  # no execute before approval

    # --- Process B: public CLI approve ---
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    assert approved["workflow_run_id"] == run_id  # same run, not a new one

    # Resume-not-rerun: plan/context schedule counts unchanged; one execute success.
    counts_after = ev.node_schedule_counts(workspace, run_id)
    assert counts_after["plan"] == counts_before["plan"]
    assert counts_after["context"] == counts_before["context"]
    assert counts_after.get("execute_stub") == 1
    assert ev.succeeded_attempt_count(workspace) == 1
    assert ev.count_rows(workspace, "execution_attempts") == 1

    # Stable ids + terminal state + settled resume op, no duplicates.
    assert ev.run_row(workspace, run_id)["thread_id"] == thread_id
    assert ev.task_status(workspace, task_id) == "completed"
    assert ev.run_status(workspace, run_id) == "completed"
    assert len(ev.approvals(workspace)) == 1
    ops = ev.resume_operations(workspace)
    assert len(ops) == 1
    assert ops[0]["decision"] == "approved"
    assert ops[0]["status"] == "completed"


# ---------------------------------------------------------------------------
# Scenario B — restart then reject
# ---------------------------------------------------------------------------


def test_scenario_b_restart_then_reject(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    run_id = str(_pause(workspace, task_id)["workflow_run_id"])

    rejected = expect_ok("reject", cli_reject(workspace, task_id, reason="not in scope"))
    assert rejected["status"] == "rejected"

    assert ev.task_status(workspace, task_id) == "rejected"
    # WorkflowRun has no REJECTED state; a rejected task's run terminates COMPLETED
    # (locked CP7 mapping: final_outcome "rejected" -> run COMPLETED, task REJECTED).
    assert ev.run_status(workspace, run_id) == "completed"
    assert ev.count_rows(workspace, "execution_attempts") == 0  # zero worker invocation
    approvals = ev.approvals(workspace)
    assert len(approvals) == 1
    assert approvals[0]["status"] == "rejected"
    ops = ev.resume_operations(workspace)
    assert len(ops) == 1
    assert ops[0]["decision"] == "rejected"
    assert ops[0]["status"] == "completed"

    # Duplicate reject is idempotent (no new approval/resume rows).
    dup = expect_ok("reject again", cli_reject(workspace, task_id, reason="not in scope"))
    assert dup["status"] == "rejected"
    assert ev.count_rows(workspace, "approvals") == 1
    assert ev.count_rows(workspace, "resume_operations") == 1

    # Approve after reject → conflicting decision → ApprovalStateConflict (exit 5).
    after = cli_approve(workspace, task_id)
    assert after.returncode == 5
    assert after.json()["error"]["type"] == "ApprovalStateConflict"


# ---------------------------------------------------------------------------
# Scenario C — restart then cancel while AWAITING
# ---------------------------------------------------------------------------


def test_scenario_c_restart_then_cancel_awaiting(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    run_id = str(_pause(workspace, task_id)["workflow_run_id"])

    cancelled = expect_ok("cancel", cli_cancel(workspace, task_id))
    assert cancelled["status"] == "cancelled"

    assert ev.task_status(workspace, task_id) == "cancelled"
    assert ev.run_status(workspace, run_id) == "cancelled"
    assert ev.count_rows(workspace, "execution_attempts") == 0  # zero worker invocation
    approvals = ev.approvals(workspace)
    assert len(approvals) == 1
    assert approvals[0]["status"] == "cancelled"
    ops = ev.resume_operations(workspace)
    assert len(ops) == 1
    assert ops[0]["decision"] == "cancelled"
    assert ops[0]["status"] == "completed"

    # Duplicate cancel is idempotent.
    dup = expect_ok("cancel again", cli_cancel(workspace, task_id))
    assert dup["status"] == "cancelled"
    assert ev.count_rows(workspace, "resume_operations") == 1

    # Approve after cancel → conflicting decision → ApprovalStateConflict (exit 5).
    after = cli_approve(workspace, task_id)
    assert after.returncode == 5
    assert after.json()["error"]["type"] == "ApprovalStateConflict"
