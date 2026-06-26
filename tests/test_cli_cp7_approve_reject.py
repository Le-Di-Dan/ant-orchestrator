"""CP7 — ``ant approve`` / ``ant reject`` command tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.enums import ApprovalStatus
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME
from tests.support.cli_cp7 import (  # noqa: F401  (nest is a fixture)
    cli,
    nest,
    seed_awaiting,
    seed_owned_resume,
)


def _approval_actor(root: Path) -> tuple[str, str | None, str | None]:
    with sqlite3.connect(str(root / ANT_DIRNAME / DATABASE_FILENAME)) as conn:
        row = conn.execute("SELECT status, actor_source, actor_label FROM approvals").fetchone()
    return row[0], row[1], row[2]


def test_approve_pending_completes_and_persists_actor(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    result = cli.invoke(app, ["approve", "T1", "--by", "alice"])
    assert result.exit_code == 0
    assert "Status: completed" in result.stdout
    status, source, label = _approval_actor(nest)
    assert status == "approved"
    assert source == "local_cli"
    assert label == "alice"


def test_approve_json_schema(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    result = cli.invoke(app, ["approve", "T1", "--json"])
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert payload["command"] == "approve"
    assert payload["status"] == "completed"


def test_approve_idempotent_retry(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    first = cli.invoke(app, ["approve", "T1"])
    second = cli.invoke(app, ["approve", "T1", "--json"])
    assert first.exit_code == 0
    assert second.exit_code == 0
    assert json.loads(second.stdout)["status"] == "completed"


def test_approve_conflicting_decision_exits_5(nest: Path) -> None:  # noqa: F811
    _worker, run_id, approval_id = seed_awaiting(nest)
    seed_owned_resume(nest, run_id, approval_id, ApprovalStatus.REJECTED)
    result = cli.invoke(app, ["approve", "T1", "--json"])
    assert result.exit_code == 5
    assert json.loads(result.stdout)["error"]["type"] == "ApprovalStateConflict"


def test_reject_requires_reason(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    result = cli.invoke(app, ["reject", "T1"])
    assert result.exit_code == 2


def test_reject_empty_reason_exits_2(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    result = cli.invoke(app, ["reject", "T1", "--reason", "   "])
    assert result.exit_code == 2


def test_reject_pending_rejects_without_worker(nest: Path) -> None:  # noqa: F811
    worker, _run_id, _approval_id = seed_awaiting(nest)
    calls_before = worker.calls
    result = cli.invoke(app, ["reject", "T1", "--reason", "not safe", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["status"] == "rejected"
    assert worker.calls == calls_before


def test_reject_duplicate_idempotent(nest: Path) -> None:  # noqa: F811
    seed_awaiting(nest)
    cli.invoke(app, ["reject", "T1", "--reason", "no"])
    second = cli.invoke(app, ["reject", "T1", "--reason", "no", "--json"])
    assert second.exit_code == 0
    assert json.loads(second.stdout)["status"] == "rejected"
