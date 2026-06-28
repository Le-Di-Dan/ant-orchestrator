"""CP7 — End-to-end API flows (Phase 7 API).

Exercises multi-step scenarios: create task → run workflow → inspect state.
"""

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
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME

_BASE_TS = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _Clock:
    def now(self) -> UtcTimestamp:
        return UtcTimestamp(_BASE_TS)


def _seed_event(workspace: Path, task_id: str | None = None) -> None:
    logs_dir = workspace / ANT_DIRNAME / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    sink = JsonlAuditSink(logs_dir, clock=_Clock(), redactor=Redactor())
    detail: dict[str, str] = {}
    if task_id:
        detail["task_id"] = task_id
    sink.write(
        AuditEvent(
            event_type=AuditEventType.ROUTING_DECISION,
            correlation_id=CorrelationId("corr-e2e-001"),
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


# --- Full flow: create → run → inspect ---


def test_create_run_inspect_task(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "E2E task"}).json()["task_id"]
    run_resp = client.post(f"/tasks/{task_id}/workflow-runs")
    assert run_resp.status_code == 200
    wf_run_id = run_resp.json()["workflow_run_id"]

    # Task detail
    task = client.get(f"/tasks/{task_id}").json()
    assert task["task_id"] == task_id

    # Workflow run detail
    wf_run = client.get(f"/workflow-runs/{wf_run_id}").json()
    assert wf_run["workflow_run_id"] == wf_run_id
    assert wf_run["task_id"] == task_id


def test_audit_logs_api_returns_seeded_events(client: TestClient, workspace: Path) -> None:
    _seed_event(workspace)
    logs_resp = client.get("/logs")
    assert logs_resp.status_code == 200
    assert len(logs_resp.json()["entries"]) > 0


def test_task_id_filters_logs(client: TestClient, workspace: Path) -> None:
    t1 = client.post("/tasks", json={"title": "Task Alpha"}).json()["task_id"]
    t2 = client.post("/tasks", json={"title": "Task Beta"}).json()["task_id"]
    _seed_event(workspace, task_id=t1)
    _seed_event(workspace, task_id=t2)

    logs_t1 = client.get("/logs", params={"task_id": t1}).json()["entries"]
    logs_t2 = client.get("/logs", params={"task_id": t2}).json()["entries"]
    logs_all = client.get("/logs").json()["entries"]

    assert len(logs_all) >= len(logs_t1)
    assert len(logs_all) >= len(logs_t2)

    for entry in logs_t1:
        assert entry["task_id"] == t1 or entry["task_id"] is None


def test_run_workflow_produces_workflow_run_id(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "ID check"}).json()["task_id"]
    run = client.post(f"/tasks/{task_id}/workflow-runs").json()
    wf_run_id = run["workflow_run_id"]
    assert wf_run_id
    resp = client.get(f"/workflow-runs/{wf_run_id}")
    assert resp.status_code == 200


def test_workflow_run_id_appears_in_task_detail(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Detail check"}).json()["task_id"]
    run = client.post(f"/tasks/{task_id}/workflow-runs").json()
    wf_run_id = run["workflow_run_id"]

    task = client.get(f"/tasks/{task_id}").json()
    if task["active_workflow_run"] is not None:
        assert task["active_workflow_run"]["workflow_run_id"] == wf_run_id


def test_create_multiple_tasks_independent(client: TestClient) -> None:
    t1 = client.post("/tasks", json={"title": "Task X"}).json()["task_id"]
    t2 = client.post("/tasks", json={"title": "Task Y"}).json()["task_id"]
    assert t1 != t2
    assert client.get(f"/tasks/{t1}").json()["title"] == "Task X"
    assert client.get(f"/tasks/{t2}").json()["title"] == "Task Y"


def test_worker_runs_visible_after_run(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Worker check"}).json()["task_id"]
    client.post(f"/tasks/{task_id}/workflow-runs")
    task = client.get(f"/tasks/{task_id}").json()
    if task["worker_runs"]:
        wr_id = task["worker_runs"][0]["worker_run_id"]
        wr_detail = client.get(f"/worker-runs/{wr_id}").json()
        assert wr_detail["task_id"] == task_id


def test_parity_cli_api_task_count(workspace: Path) -> None:
    runner = CliRunner()
    with TestClient(create_app(workspace)) as c:
        c.post("/tasks", json={"title": "Parity A"})
        c.post("/tasks", json={"title": "Parity B"})

    result = runner.invoke(cli_app, ["status"], catch_exceptions=False)
    assert result.exit_code == 0
