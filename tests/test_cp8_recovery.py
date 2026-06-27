"""CP8 — Scenario H: fail-closed recovery across a process boundary (subprocess).

Process A is the test-only driver, which durably reproduces a specific crash window
(interrupt checkpoint without PauseFinalizer; END checkpoint without
CompletionFinalizer; a RUNNING run never invoked; a RUNNING run whose observed
checkpoint is gone) and then exits. Process B is the *public* ``ant`` CLI, which
re-opens the durable state and either repairs it idempotently or fails closed. Schema
and definition version mismatches are exercised against the real runner guard.
"""

from __future__ import annotations

from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import cli_run, driver, expect_ok, init_and_create


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


# ---------------------------------------------------------------------------
# Crash #2 — interrupt checkpoint durable, Approval not finalized
# ---------------------------------------------------------------------------


def test_crash2_interrupt_refinalized_without_resume(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    crashed = expect_ok(
        "crash-interrupt",
        driver("crash-interrupt", workspace, task_id=task_id, extra=["--significant-write"]),
    )
    run_id = str(crashed["workflow_run_id"])
    # Durable interrupt checkpoint, but no Approval / terminal yet.
    assert ev.run_status(workspace, run_id) == "running"
    assert ev.count_rows(workspace, "approvals") == 0

    # Process B: detect INTERRUPTED → PauseFinalizer → AWAITING (no resume, no worker).
    recovered = expect_ok("run", cli_run(workspace, task_id))
    assert recovered["status"] == "waiting_for_approval"
    assert ev.run_status(workspace, run_id) == "awaiting_approval"
    assert ev.count_rows(workspace, "approvals") == 1
    assert ev.count_rows(workspace, "execution_attempts") == 0  # never resumed/executed

    # Idempotent: re-running does not create a second Approval.
    again = expect_ok("run again", cli_run(workspace, task_id))
    assert again["status"] == "waiting_for_approval"
    assert ev.count_rows(workspace, "approvals") == 1


# ---------------------------------------------------------------------------
# Crash #7 — END checkpoint durable, Task/Run not terminal
# ---------------------------------------------------------------------------


def test_crash7_end_finalized_without_rerun(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    crashed = expect_ok(
        "crash-end",
        driver("crash-end", workspace, task_id=task_id, extra=["--fallback", "success"]),
    )
    run_id = str(crashed["workflow_run_id"])
    assert ev.run_status(workspace, run_id) == "running"  # CompletionFinalizer never ran
    attempts_before = ev.count_rows(workspace, "execution_attempts")
    assert attempts_before == 1  # the crashed invoke reached END after one execute

    # Process B: CompletionFinalizer runs; the graph is NOT re-run, the worker NOT recalled.
    recovered = expect_ok("run", cli_run(workspace, task_id))
    assert recovered["status"] == "completed"
    assert ev.task_status(workspace, task_id) == "completed"
    assert ev.run_status(workspace, run_id) == "completed"
    assert ev.count_rows(workspace, "execution_attempts") == attempts_before


# ---------------------------------------------------------------------------
# Initial invoke never happened — safe to re-START
# ---------------------------------------------------------------------------


def test_initial_not_invoked_reinvokes_from_start(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    seeded = expect_ok("seed-running", driver("seed-running", workspace, task_id=task_id))
    run_id = str(seeded["workflow_run_id"])
    assert ev.count_rows(workspace, "approvals") == 0
    assert ev.count_rows(workspace, "execution_attempts") == 0
    assert ev.checkpoint_count(workspace, run_id) == 0  # nothing ever invoked

    # Process B: no checkpoint observed + no progress → re-invoke from START → completes.
    recovered = expect_ok("run", cli_run(workspace, task_id))
    assert recovered["status"] == "completed"
    assert ev.task_status(workspace, task_id) == "completed"


# ---------------------------------------------------------------------------
# Checkpoint lost after progress — fail closed (never re-START)
# ---------------------------------------------------------------------------


def test_lost_checkpoint_after_progress_fails_closed(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    # RUNNING run that observed a checkpoint which is now absent.
    expect_ok(
        "seed-running", driver("seed-running", workspace, task_id=task_id, extra=["--observed"])
    )
    proc = cli_run(workspace, task_id)

    assert proc.returncode == 4
    assert proc.json()["error"]["type"] == "CheckpointRecoveryError"
    # Fail closed: no re-START, no worker, no checkpoint fabricated.
    assert ev.count_rows(workspace, "execution_attempts") == 0


# ---------------------------------------------------------------------------
# Version mismatches — fail closed at the runner guard (typed, sanitized)
# ---------------------------------------------------------------------------


def test_graph_state_schema_mismatch_fails_closed(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    proc = driver("schema-mismatch", workspace, task_id=task_id)

    assert proc.returncode != 0
    error = proc.json()["error"]
    assert error["type"] == "GraphStateSchemaMismatch"
    assert "Traceback" not in proc.stdout


def test_workflow_definition_mismatch_fails_closed(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    proc = driver("definition-mismatch", workspace, task_id=task_id)

    assert proc.returncode != 0
    error = proc.json()["error"]
    assert error["type"] == "WorkflowDefinitionMismatch"
    assert "Traceback" not in proc.stdout
