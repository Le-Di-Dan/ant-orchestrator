"""CP8 correction — conflicting-decision matrix across processes (subprocess).

Rule under test: a resolve on an already-terminal task compares the requested
decision against the *persisted* decision before returning. Same decision →
idempotent terminal (exit 0); different decision → ApprovalStateConflict (exit 5).
Each case drives the gate to AWAITING via the driver, then issues two public-CLI
decisions in separate processes.
"""

from __future__ import annotations

from pathlib import Path

from tests.support.cp8_harness import (
    cli_approve,
    cli_cancel,
    cli_reject,
    driver,
    expect_ok,
    init_and_create,
)


def _awaiting(tmp_path: Path) -> tuple[Path, str]:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    task_id = init_and_create(workspace)
    expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )
    return workspace, task_id


def _assert_conflict(proc: object) -> None:
    assert proc.returncode == 5, (proc.returncode, proc.stdout)  # type: ignore[attr-defined]
    assert proc.json()["error"]["type"] == "ApprovalStateConflict"  # type: ignore[attr-defined]


# ---- same decision → idempotent terminal (exit 0) -------------------------


def test_reject_then_reject_is_idempotent(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    assert cli_reject(workspace, task_id, reason="no").returncode == 0
    again = cli_reject(workspace, task_id, reason="no")
    assert again.returncode == 0
    assert again.json()["status"] == "rejected"


def test_cancel_then_cancel_is_idempotent(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    assert cli_cancel(workspace, task_id).returncode == 0
    again = cli_cancel(workspace, task_id)
    assert again.returncode == 0
    assert again.json()["status"] == "cancelled"


# ---- different decision → ApprovalStateConflict (exit 5) -------------------


def test_reject_then_approve_conflicts(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    assert cli_reject(workspace, task_id, reason="no").returncode == 0
    _assert_conflict(cli_approve(workspace, task_id))


def test_cancel_then_approve_conflicts(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    assert cli_cancel(workspace, task_id).returncode == 0
    _assert_conflict(cli_approve(workspace, task_id))


def test_cancel_then_reject_conflicts(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    assert cli_cancel(workspace, task_id).returncode == 0
    _assert_conflict(cli_reject(workspace, task_id, reason="no"))


def test_approve_then_reject_conflicts(tmp_path: Path) -> None:
    workspace, task_id = _awaiting(tmp_path)
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    _assert_conflict(cli_reject(workspace, task_id, reason="no"))
