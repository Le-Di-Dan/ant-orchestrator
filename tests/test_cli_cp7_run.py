"""CP7 — ``ant run <task-id>`` command tests.

Note: the production composition uses the deterministic stub worker, which never
requires approval, so a vanilla ``run`` always COMPLETES. AWAITING_APPROVAL behaviour
is exercised by seeding the paused state (an interrupt runner writes a real checkpoint)
and re-entering it through ``ant run`` — proving the command does not bypass the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.cli.main import app
from tests.support.cli_cp7 import cli, nest, seed_awaiting  # noqa: F401  (nest is a fixture)


def _create_task(title: str = "demo") -> str:
    result = cli.invoke(app, ["task", "create", "--title", title, "--json"])
    assert result.exit_code == 0
    return str(json.loads(result.stdout)["task_id"])


def test_run_created_to_completed(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    result = cli.invoke(app, ["run", task_id])
    assert result.exit_code == 0
    assert "Status: completed" in result.stdout
    assert task_id in result.stdout


def test_run_json_schema_version(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    result = cli.invoke(app, ["run", task_id, "--json"])
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["command"] == "run"
    assert payload["status"] == "completed"
    assert payload["workflow_run_id"]


def test_run_on_awaiting_does_not_bypass_gate(nest: Path) -> None:  # noqa: F811
    worker, _run_id, _approval_id = seed_awaiting(nest)
    calls_before = worker.calls
    result = cli.invoke(app, ["run", "T1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "waiting_for_approval"
    assert payload["pending_approval"] is not None
    # Re-entry must not invoke the worker (the gate was not approved).
    assert worker.calls == calls_before


def test_run_terminal_task_is_state_conflict(nest: Path) -> None:  # noqa: F811
    task_id = _create_task()
    cli.invoke(app, ["run", task_id])  # → completed (terminal)
    result = cli.invoke(app, ["run", task_id, "--json"])
    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["type"] == "WorkflowStateError"


def test_run_unknown_task_maps_to_storage_exit(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["run", "no-such-task", "--json"])
    assert result.exit_code == 4
    assert json.loads(result.stdout)["error"]["type"] == "RecordNotFound"
