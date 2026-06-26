"""CP7 — ``ant status`` command tests."""

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

_TASK_KEYS = {
    "task_id",
    "status",
    "priority",
    "workflow_run_id",
    "run_status",
    "pending_gate_type",
    "cancel_requested",
}


def _status_json(args: list[str] | None = None) -> dict:
    result = cli.invoke(app, ["status", "--json", *(args or [])])
    assert result.exit_code == 0
    return dict(json.loads(result.stdout))


def test_status_empty_workspace(nest: Path) -> None:  # noqa: F811
    text = cli.invoke(app, ["status"])
    assert text.exit_code == 0
    assert "State: ready" in text.stdout
    payload = _status_json()
    assert payload["total"] == 0
    assert payload["tasks"] == []
    assert payload["workspace"]["ready"] is True


def test_status_active_run(nest: Path) -> None:  # noqa: F811
    seed_running(nest)
    row = _status_json()["tasks"][0]
    assert row["run_status"] == "running"
    assert row["cancel_requested"] is False


def test_status_pending_approval_gate_type(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    row = _status_json()["tasks"][0]
    assert row["status"] == "waiting_for_approval"
    assert row["pending_gate_type"] == "significant_write"


def test_status_cancel_requested(nest: Path) -> None:  # noqa: F811
    seed_running(nest)
    cli.invoke(app, ["cancel", "T1"])
    row = _status_json()["tasks"][0]
    assert row["cancel_requested"] is True


def test_status_terminal_task(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", "demo", "--json"])
    task_id = json.loads(result.stdout)["task_id"]
    cli.invoke(app, ["run", task_id])
    row = _status_json()["tasks"][0]
    assert row["status"] == "completed"
    assert row["workflow_run_id"] is None


def test_status_deterministic_ordering(nest: Path) -> None:  # noqa: F811
    for i in range(3):
        cli.invoke(app, ["task", "create", "--title", f"t{i}"])
    first = [row["task_id"] for row in _status_json()["tasks"]]
    second = [row["task_id"] for row in _status_json()["tasks"]]
    assert first == second
    assert len(first) == 3


def test_status_redaction_only_whitelisted_keys(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    payload = _status_json()
    assert set(payload["tasks"][0].keys()) == _TASK_KEYS
    # No raw request payload / checkpoint channel leaks into the document.
    blob = json.dumps(payload)
    assert "request_json" not in blob
    assert "checkpoint" not in blob
