"""CP7 — POST /tasks, POST /tasks/{id}/workflow-runs, GET /tasks/{id} (Phase 7 API)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ant_orchestrator.api.main import create_app
from ant_orchestrator.cli.main import app as cli_app


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


# --- POST /tasks ---


def test_create_task_success_201(client: TestClient) -> None:
    resp = client.post("/tasks", json={"title": "Alpha task"})
    assert resp.status_code == 201
    data = resp.json()
    assert data["task_id"]
    assert data["title"] == "Alpha task"
    assert data["status"] == "created"
    assert data["priority"] == "normal"
    assert data["source"] == "cli"
    assert data["created_at"]


def test_create_task_with_priority(client: TestClient) -> None:
    resp = client.post("/tasks", json={"title": "High priority", "priority": "high"})
    assert resp.status_code == 201
    assert resp.json()["priority"] == "high"


def test_create_task_missing_title_422(client: TestClient) -> None:
    resp = client.post("/tasks", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body


def test_create_task_extra_fields_forbidden(client: TestClient) -> None:
    resp = client.post("/tasks", json={"title": "T", "secret": "x"})
    assert resp.status_code == 422


def test_create_task_no_workflow_run_created(client: TestClient, workspace: Path) -> None:
    resp = client.post("/tasks", json={"title": "NoRun"})
    assert resp.status_code == 201
    task_id = resp.json()["task_id"]
    detail = client.get(f"/tasks/{task_id}").json()
    assert detail["active_workflow_run"] is None
    assert detail["worker_runs"] == []


# --- POST /tasks/{task_id}/workflow-runs ---


def test_run_workflow_new_run_200(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Run me"}).json()["task_id"]
    resp = client.post(f"/tasks/{task_id}/workflow-runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_run_id"]
    assert data["status"]


def test_run_workflow_missing_task_404(client: TestClient) -> None:
    resp = client.post("/tasks/nonexistent-id/workflow-runs")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_run_workflow_terminal_task_422(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Terminal"}).json()["task_id"]
    client.post(f"/tasks/{task_id}/workflow-runs")
    # Run again on terminal task
    resp = client.post(f"/tasks/{task_id}/workflow-runs")
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_run_workflow_active_run_resume(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Approval task"}).json()["task_id"]
    r1 = client.post(f"/tasks/{task_id}/workflow-runs").json()
    if r1["status"] == "waiting_for_approval":
        r2 = client.post(f"/tasks/{task_id}/workflow-runs")
        assert r2.status_code == 200
        assert r2.json()["workflow_run_id"] == r1["workflow_run_id"]


# --- GET /tasks/{task_id} ---


def test_get_task_success(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Get me"}).json()["task_id"]
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == task_id
    assert data["title"] == "Get me"
    assert "energy_totals" in data
    assert "approvals" in data
    assert "worker_runs" in data


def test_get_task_missing_404(client: TestClient) -> None:
    resp = client.get("/tasks/no-such-task")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_get_task_energy_visible(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Energy check"}).json()["task_id"]
    client.post(f"/tasks/{task_id}/workflow-runs")
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    energy = resp.json()["energy_totals"]
    assert "tokens_in" in energy
    assert "tokens_out" in energy
    assert "record_count" in energy


def test_get_task_worker_runs_visible_after_run(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "WorkerRun check"}).json()["task_id"]
    client.post(f"/tasks/{task_id}/workflow-runs")
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    worker_runs = resp.json()["worker_runs"]
    assert isinstance(worker_runs, list)


def test_get_task_approval_visible(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Approval check"}).json()["task_id"]
    run_resp = client.post(f"/tasks/{task_id}/workflow-runs").json()
    resp = client.get(f"/tasks/{task_id}")
    assert resp.status_code == 200
    approvals = resp.json()["approvals"]
    assert isinstance(approvals, list)
    if run_resp.get("status") == "waiting_for_approval":
        assert len(approvals) >= 1
