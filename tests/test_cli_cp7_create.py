"""CP7 — ``ant task create`` command tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ant_orchestrator.cli.main import app
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME
from tests.support.cli_cp7 import cli, count_rows, nest  # noqa: F401  (nest is a fixture)


def test_create_text_shows_id_and_status(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", "demo"])
    assert result.exit_code == 0
    assert "Task:" in result.stdout
    assert "Status: created" in result.stdout


def test_create_json_shape(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", "demo", "--priority", "high", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["command"] == "task_create"
    assert payload["status"] == "created"
    assert payload["priority"] == "high"
    assert payload["task_id"]


def test_create_invalid_priority_exits_2(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", "demo", "--priority", "bogus"])
    assert result.exit_code == 2


def test_create_empty_title_exits_2(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", ""])
    assert result.exit_code == 2


def test_create_persists_created_task(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["task", "create", "--title", "demo", "--json"])
    task_id = json.loads(result.stdout)["task_id"]
    with sqlite3.connect(str(nest / ANT_DIRNAME / DATABASE_FILENAME)) as conn:
        row = conn.execute("SELECT status FROM tasks WHERE id = ?", (task_id,)).fetchone()
    assert row[0] == "created"


def test_create_makes_no_workflow_run(nest: Path) -> None:  # noqa: F811
    cli.invoke(app, ["task", "create", "--title", "demo"])
    assert count_rows(nest, "workflow_runs") == 0
