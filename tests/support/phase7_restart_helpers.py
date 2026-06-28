"""Shared helpers for Phase 7 CP8 three-level restart recovery tests.

Provides deterministic approval-pause setup and durable-state snapshot helpers
that are shared across app-instance, service-reinit, and subprocess levels.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.workspace.layout import ANT_DIRNAME
from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import driver, expect_ok, init_and_create


def setup_paused_workspace(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Init workspace, create task, drive to approval pause via driver subprocess.

    Returns (workspace, task_id, run_id, approval_id).
    Uses ``--significant-write`` intent flag to trigger the approval gate.
    """
    workspace = tmp_path / "nest"
    workspace.mkdir()
    task_id = init_and_create(workspace)
    paused = expect_ok(
        "driver-run",
        driver("run", workspace, task_id=task_id, extra=["--significant-write"]),
    )
    run_id = str(paused["workflow_run_id"])
    approval_id = str(paused["approval_id"])
    return workspace, task_id, run_id, approval_id


def count_wf_runs_for_task(workspace: Path, task_id: str) -> int:
    """Count workflow_runs rows for task_id via a fresh SQLite connection."""
    import sqlite3

    db = workspace / ANT_DIRNAME / "state.sqlite"
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM workflow_runs WHERE task_id = ?", (task_id,)
        ).fetchone()
    return int(row[0])


def count_approvals_for_run(workspace: Path, run_id: str) -> int:
    """Count approval rows for workflow_run_id via a fresh SQLite connection."""
    import sqlite3

    db = workspace / ANT_DIRNAME / "state.sqlite"
    with sqlite3.connect(str(db)) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM approvals WHERE workflow_run_id = ?", (run_id,)
        ).fetchone()
    return int(row[0])


def count_audit_events(workspace: Path) -> int:
    """Count non-empty JSONL lines in the audit logs directory."""
    logs_dir = workspace / ANT_DIRNAME / "logs"
    if not logs_dir.exists():
        return 0
    total = 0
    for f in logs_dir.glob("*.jsonl"):
        total += sum(1 for line in f.read_text(encoding="utf-8").splitlines() if line.strip())
    return total


def assert_approval_pending(workspace: Path, run_id: str) -> None:
    """Assert that exactly one pending approval exists for run_id."""
    pending = [r for r in ev.approvals(workspace) if r["status"] == "pending"]
    assert len(pending) >= 1, "expected at least one pending approval"
    assert any(r["id"] for r in pending), "pending approval must have a non-empty id"


def assert_no_duplicate_wf_runs(workspace: Path, task_id: str, baseline: int) -> None:
    """Assert that workflow run count for task_id did not increase beyond baseline."""
    current = count_wf_runs_for_task(workspace, task_id)
    assert current == baseline, f"workflow_runs count changed: expected {baseline}, got {current}"


def assert_no_duplicate_approvals(workspace: Path, run_id: str, baseline: int) -> None:
    """Assert that approval count for run_id did not increase beyond baseline."""
    current = count_approvals_for_run(workspace, run_id)
    assert current == baseline, f"approvals count changed: expected {baseline}, got {current}"
