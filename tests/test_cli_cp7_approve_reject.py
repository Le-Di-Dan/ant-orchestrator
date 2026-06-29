"""CP7 — ``ant approve`` / ``ant reject`` command tests."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.enums import ApprovalStatus
from ant_orchestrator.workers import stub
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


def test_approve_resumes_on_production_composition(
    nest: Path,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CP7 invariant: approve auto-resume must NOT run on the neutral stub composition.

    Routing approve through the neutral composition would resume the graph on
    ``DeterministicStubAdapter`` and fabricate a completed result. This pins the
    production path: the neutral ``_services`` is never used for approve, and the
    deterministic stub's ``execute`` is never called during an approve auto-resume.
    """
    seed_awaiting(nest)

    def _neutral_forbidden(_path: object) -> object:
        raise AssertionError("approve must use the production composition, not neutral _services")

    stub_calls = {"n": 0}
    original_execute = stub.DeterministicStubAdapter.execute

    def _spy_execute(self: object, intent: object) -> object:
        stub_calls["n"] += 1
        return original_execute(self, intent)  # type: ignore[arg-type]

    monkeypatch.setattr("ant_orchestrator.cli.phase4_commands._services", _neutral_forbidden)
    monkeypatch.setattr(stub.DeterministicStubAdapter, "execute", _spy_execute)

    result = cli.invoke(app, ["approve", "T1", "--json"])
    assert result.exit_code == 0, result.stdout
    assert json.loads(result.stdout)["status"] == "completed"
    assert stub_calls["n"] == 0


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
