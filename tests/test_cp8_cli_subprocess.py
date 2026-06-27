"""CP8 — public CLI smoke E2E + JSON/exit-code contract + DB separation (subprocess).

Every step is a real ``ant`` process (or the test-only driver to set up a paused
state the public CLI then operates on). Business state and checkpoints are always
re-read through fresh connections in a later process — nothing survives in memory.
"""

from __future__ import annotations

from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import (
    cli_approve,
    cli_run,
    cli_status,
    driver,
    expect_ok,
    init_and_create,
    init_nest,
    run_cli,
)

# Tables owned by LangGraph's sqlite checkpointer (must never appear in state.sqlite).
_LANGGRAPH_TABLES = {"checkpoints", "checkpoint_blobs", "checkpoint_writes", "writes"}
# Core business tables (must never appear in checkpoints.sqlite).
_BUSINESS_TABLES = {"tasks", "workflow_runs", "approvals"}

_FORBIDDEN_STDOUT = ("Traceback", "SELECT ", "INSERT ", "request_json", "request_payload")


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


# ---------------------------------------------------------------------------
# Happy-path smoke: init → create → run → status across separate processes
# ---------------------------------------------------------------------------


def test_cli_happy_path_completes_and_status_reads_terminal(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    run_payload = expect_ok("run", cli_run(workspace, task_id))
    assert run_payload["status"] == "completed"
    assert run_payload["schema_version"] == 1
    assert run_payload["pending_approval"] is None
    run_id = run_payload["workflow_run_id"]
    assert isinstance(run_id, str) and run_id

    # A brand-new process reads the terminal business state.
    status_payload = expect_ok("status", cli_status(workspace))
    rows = status_payload["tasks"]
    assert any(r["task_id"] == task_id and r["status"] == "completed" for r in rows)

    # The terminal state is durable in the business DB read with a fresh connection.
    assert ev.task_status(workspace, task_id) == "completed"
    assert ev.run_status(workspace, run_id) == "completed"
    # The END checkpoint is readable through a freshly opened checkpointer.
    assert ev.checkpoint_count(workspace, run_id) >= 1


def test_cli_run_output_is_single_clean_json_document(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    proc = cli_run(workspace, task_id)

    assert proc.returncode == 0
    # Exactly one JSON document, no stray text, no leaked internals.
    payload = proc.json()
    assert payload["command"] == "run"
    for token in _FORBIDDEN_STDOUT:
        assert token not in proc.stdout


# ---------------------------------------------------------------------------
# Database separation: business schema vs LangGraph checkpoint schema
# ---------------------------------------------------------------------------


def test_databases_keep_separate_schemas(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok("run", cli_run(workspace, task_id))

    state_tables = ev.state_tables(workspace)
    checkpoint_tables = ev.checkpoint_tables(workspace)

    assert _BUSINESS_TABLES <= state_tables
    assert state_tables.isdisjoint(_LANGGRAPH_TABLES)
    assert checkpoint_tables  # LangGraph created its own schema
    assert checkpoint_tables.isdisjoint(_BUSINESS_TABLES)


# ---------------------------------------------------------------------------
# Exit-code contract (one real process per code)
# ---------------------------------------------------------------------------


def test_exit_code_0_success(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    assert cli_run(workspace, task_id).returncode == 0


def test_exit_code_2_usage_error(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    init_nest(workspace)
    # Missing the required --title option → Typer usage error.
    proc = run_cli(["task", "create", "--path", str(workspace)])
    assert proc.returncode == 2


def test_exit_code_3_workspace_not_found(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)  # no `ant init` → no .ant/
    proc = cli_status(workspace)
    assert proc.returncode == 3
    assert proc.json()["error"]["type"] == "NestNotFound"


def test_exit_code_4_storage_recovery(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    # Seed a RUNNING run that observed a checkpoint which is now absent → fail closed.
    seed = expect_ok(
        "seed-running", driver("seed-running", workspace, task_id=task_id, extra=["--observed"])
    )
    assert isinstance(seed["workflow_run_id"], str)
    proc = cli_run(workspace, task_id)
    assert proc.returncode == 4
    assert proc.json()["error"]["type"] == "CheckpointRecoveryError"


def test_exit_code_5_state_conflict(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    # Drive to AWAITING, then simulate another process holding an in-flight REJECTED
    # resume lease. A public-CLI approve issues a different decision → conflict (exit 5).
    expect_ok(
        "driver run", driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    )
    expect_ok(
        "seed-owned-resume",
        driver("seed-owned-resume", workspace, task_id=task_id, extra=["--decision", "rejected"]),
    )
    proc = cli_approve(workspace, task_id)
    assert proc.returncode == 5
    assert proc.json()["error"]["type"] == "ApprovalStateConflict"


def test_exit_code_6_approval_rule_violation(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    # Approve a CREATED task that has no active run / pending gate.
    proc = cli_approve(workspace, task_id)
    assert proc.returncode == 6
    assert proc.json()["error"]["type"] == "ApprovalRuleViolation"


# ---------------------------------------------------------------------------
# JSON error contract: sanitized, single document, on stdout
# ---------------------------------------------------------------------------


def test_json_error_is_sanitized_single_document(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    proc = cli_approve(workspace, task_id)  # exit 6, JSON error on stdout

    payload = proc.json()  # parses as exactly one document
    assert payload["schema_version"] == 1
    assert set(payload["error"]) == {"type", "message"}
    for token in _FORBIDDEN_STDOUT:
        assert token not in proc.stdout
