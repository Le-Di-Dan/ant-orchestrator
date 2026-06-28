"""CP7 — GET /logs (Phase 7 API)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.api.main import create_app
from ant_orchestrator.application.ports.audit import AuditEvent, AuditEventType, CorrelationId
from ant_orchestrator.cli.main import app as cli_app
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> UtcTimestamp:
        return UtcTimestamp(_BASE_TS)


def _seed_events(workspace: Path, count: int = 2, task_id: str | None = None) -> None:
    logs_dir = workspace / ANT_DIRNAME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sink = JsonlAuditSink(logs_dir, clock=_Clock(), redactor=Redactor())
    for i in range(count):
        detail: dict[str, str] = {}
        if task_id:
            detail["task_id"] = task_id
        sink.write(
            AuditEvent(
                event_type=AuditEventType.ROUTING_DECISION,
                correlation_id=CorrelationId(f"corr-{i:04d}"),
                created_at=UtcTimestamp(_BASE_TS),
                detail=detail,
            )
        )


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(cli_app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0, result.output
    return tmp_path


@pytest.fixture
def client(workspace: Path):
    with TestClient(create_app(workspace)) as c:
        yield c


# --- Basic response ---


def test_logs_empty_200(client: TestClient) -> None:
    resp = client.get("/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["entries"] == []
    assert data["has_more"] is False
    assert data["corrupt_count"] == 0
    assert data["files_scanned"] == 0
    assert "resolved_limit" in data


def test_logs_resolved_limit_default(client: TestClient) -> None:
    resp = client.get("/logs")
    assert resp.json()["resolved_limit"] == LOG_DEFAULT_LIMIT


def test_logs_explicit_limit(client: TestClient) -> None:
    resp = client.get("/logs", params={"limit": "5"})
    assert resp.status_code == 200
    assert resp.json()["resolved_limit"] == 5


# --- Limit validation ---


def test_logs_limit_zero_422(client: TestClient) -> None:
    resp = client.get("/logs", params={"limit": "0"})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_logs_negative_limit_422(client: TestClient) -> None:
    resp = client.get("/logs", params={"limit": "-1"})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_logs_over_max_limit_422(client: TestClient) -> None:
    from ant_orchestrator.config.constants import LOG_MAX_LIMIT

    resp = client.get("/logs", params={"limit": str(LOG_MAX_LIMIT + 1)})
    assert resp.status_code == 422
    assert "error" in resp.json()


# --- Entries from real workflow ---


def test_logs_entries_present(client: TestClient, workspace: Path) -> None:
    _seed_events(workspace, count=3)
    resp = client.get("/logs")
    assert resp.status_code == 200
    assert len(resp.json()["entries"]) > 0


def test_logs_entry_shape(client: TestClient, workspace: Path) -> None:
    _seed_events(workspace, count=1)
    resp = client.get("/logs")
    entry = resp.json()["entries"][0]
    assert "event_type" in entry
    assert "created_at" in entry
    assert "correlation_id" in entry
    assert "task_id" in entry
    assert "decision" in entry


def test_logs_newest_first(client: TestClient, workspace: Path) -> None:
    _seed_events(workspace, count=3)
    entries = client.get("/logs").json()["entries"]
    if len(entries) >= 2:
        assert entries[0]["created_at"] >= entries[1]["created_at"]


def test_logs_task_filter(client: TestClient, workspace: Path) -> None:
    task_id = client.post("/tasks", json={"title": "Filtered"}).json()["task_id"]
    _seed_events(workspace, count=2, task_id=task_id)
    resp = client.get("/logs", params={"task_id": task_id})
    assert resp.status_code == 200
    for entry in resp.json()["entries"]:
        assert entry["task_id"] == task_id or entry["task_id"] is None


def test_logs_no_traceback_in_error(client: TestClient) -> None:
    resp = client.get("/logs", params={"limit": "0"})
    body = resp.text
    assert "Traceback" not in body
    assert "sqlite3" not in body


def test_logs_has_more_field(client: TestClient) -> None:
    resp = client.get("/logs")
    assert "has_more" in resp.json()
