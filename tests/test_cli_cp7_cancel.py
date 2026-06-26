"""CP7 — ``ant cancel <task-id>`` command tests."""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.cli.main import app
from tests.support.cli_cp7 import (  # noqa: F401  (nest is a fixture)
    cli,
    nest,
    seed_awaiting,
    seed_running,
)


def _create_task(title: str = "demo") -> str:
    result = cli.invoke(app, ["task", "create", "--title", title, "--json"])
    return str(json.loads(result.stdout)["task_id"])


def test_cancel_created_to_cancelled(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    result = cli.invoke(app, ["cancel", task_id])
    assert result.exit_code == 0
    assert "Status: cancelled" in result.stdout


def test_cancel_created_json(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    result = cli.invoke(app, ["cancel", task_id, "--json"])
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["command"] == "cancel"
    assert payload["status"] == "cancelled"


def test_cancel_awaiting_to_cancelled(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    result = cli.invoke(app, ["cancel", "T1", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "cancelled"


def test_cancel_running_returns_cancel_requested(nest: Path) -> None:  # noqa: F811
    run_id = seed_running(nest)
    result = cli.invoke(app, ["cancel", "T1", "--json"])
    # Non-blocking: returns immediately with the requested marker, not a terminal state.
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "cancel_requested"
    assert payload["workflow_run_id"] == run_id


def test_cancel_duplicate_idempotent(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    cli.invoke(app, ["cancel", task_id])
    second = cli.invoke(app, ["cancel", task_id, "--json"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["status"] == "cancelled"


def test_cancel_running_duplicate_idempotent(nest: Path) -> None:  # noqa: F811
    seed_running(nest)
    cli.invoke(app, ["cancel", "T1"])
    second = cli.invoke(app, ["cancel", "T1", "--json"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["status"] == "cancel_requested"
