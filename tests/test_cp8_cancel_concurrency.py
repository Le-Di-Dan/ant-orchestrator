"""CP8 — cancel RUNNING (eventual terminal), idempotency, and concurrent approve.

Cancel-of-RUNNING and the concurrent-approve race are driven entirely through the
public ``ant`` CLI; only the initial RUNNING-with-no-checkpoint state (which the
vanilla CLI never leaves behind, since ``ant run`` always drives to a terminal or
paused state) is seeded by the test-only driver. The concurrent approve launches two
real processes via a thread pool (no sleep) and relies on the real SQLite
``UNIQUE(approval_id)`` resume-operation index to elect a single owner.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import (
    cli_approve,
    cli_cancel,
    cli_run,
    cli_status,
    driver,
    expect_ok,
    init_and_create,
)


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


# ---------------------------------------------------------------------------
# Cancel RUNNING — CANCEL_REQUESTED now, CANCELLED eventually (3 processes)
# ---------------------------------------------------------------------------


def test_cancel_running_reaches_eventual_cancelled(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    # Process A: seed a RUNNING run at a boundary where cancel intent can be written.
    seeded = expect_ok("seed-running", driver("seed-running", workspace, task_id=task_id))
    run_id = str(seeded["workflow_run_id"])

    # Process B: cancel returns CANCEL_REQUESTED immediately (does not block).
    requested = expect_ok("cancel", cli_cancel(workspace, task_id))
    assert requested["status"] == "cancel_requested"
    assert ev.run_row(workspace, run_id)["cancel_requested_at"] is not None

    # Process C: the next run reconciles the graph to a safe boundary → CANCELLED.
    reconciled = expect_ok("run", cli_run(workspace, task_id))
    assert reconciled["status"] == "cancelled"

    # No worker attempt was ever started after the cancel was observed.
    assert ev.count_rows(workspace, "execution_attempts") == 0
    assert ev.task_status(workspace, task_id) == "cancelled"
    assert ev.run_status(workspace, run_id) == "cancelled"

    # Process D: a fresh status process confirms the durable terminal state.
    status = expect_ok("status", cli_status(workspace))
    assert any(r["task_id"] == task_id and r["status"] == "cancelled" for r in status["tasks"])

    # CANCELLED is terminal and is never overwritten: a further run is rejected as
    # already-terminal (exit 5) and the durable status stays CANCELLED.
    again = cli_run(workspace, task_id)
    assert again.returncode == 5
    assert again.json()["error"]["type"] == "WorkflowStateError"
    assert ev.run_status(workspace, run_id) == "cancelled"


# ---------------------------------------------------------------------------
# Idempotency across processes
# ---------------------------------------------------------------------------


def test_run_again_while_awaiting_does_not_bypass_gate(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )

    # A second run on an AWAITING task returns AWAITING without creating a new gate.
    again = expect_ok("run", cli_run(workspace, task_id))
    assert again["status"] == "waiting_for_approval"
    assert ev.count_rows(workspace, "approvals") == 1
    assert ev.count_rows(workspace, "execution_attempts") == 0


def test_duplicate_approve_reuses_resume_operation(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )

    first = expect_ok("approve", cli_approve(workspace, task_id))
    assert first["status"] == "completed"
    second = expect_ok("approve again", cli_approve(workspace, task_id))
    assert second["status"] == "completed"

    # Idempotent: no duplicate resume operation, approval row or execute attempt.
    assert ev.count_rows(workspace, "resume_operations") == 1
    assert ev.count_rows(workspace, "approvals") == 1
    assert ev.count_rows(workspace, "execution_attempts") == 1


# ---------------------------------------------------------------------------
# Concurrent approve — exactly one owner resumes (real UNIQUE/CAS)
# ---------------------------------------------------------------------------


def test_concurrent_approve_single_owner_resumes(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )

    # Launch two real ``ant approve`` processes as close to simultaneously as the OS
    # allows (thread pool, no sleep). The SQLite UNIQUE(approval_id) index elects one.
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(cli_approve, workspace, task_id) for _ in range(2)]
        results = [f.result() for f in futures]

    # Each process ends with a deterministic, contract-valid outcome: the owner resumes
    # to completion (exit 0); the loser, having taken the write lock only after the owner
    # committed run→RUNNING, is cleanly rejected (exit 6, gate no longer pending) or — if
    # the owner already finalized — returns the terminal status idempotently (exit 0).
    codes = sorted(proc.returncode for proc in results)
    assert codes in ([0, 0], [0, 6]), [(p.returncode, p.stdout) for p in results]
    assert any(p.returncode == 0 and p.json().get("status") == "completed" for p in results)

    # System invariants regardless of who won: exactly one owner, one resume, one
    # worker invocation, one terminal finalization, no duplicate evidence.
    ops = ev.resume_operations(workspace)
    assert len(ops) == 1
    assert ev.count_rows(workspace, "execution_attempts") == 1
    assert ev.succeeded_attempt_count(workspace) == 1
    assert ev.count_rows(workspace, "approvals") == 1
    assert ev.task_status(workspace, task_id) == "completed"
    # Exactly one approval-resolution transition (no duplicate transition rows).
    approve_transitions = [
        r for r in ev.transitions(workspace, trigger="approve") if r["subject"] == "approval"
    ]
    assert len(approve_transitions) == 1
