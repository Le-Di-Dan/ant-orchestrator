"""CP7 — GET /workflow-runs/{id}, GET /worker-runs/{id}, app isolation (Phase 7 API)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from ant_orchestrator.api.main import create_app
from ant_orchestrator.cli.main import app as cli_app
from ant_orchestrator.core.domain.entities import WorkerRun
from ant_orchestrator.core.domain.enums import WorkerRunStatus
from ant_orchestrator.core.domain.records import EnergyUsage
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.energy_usage import SqliteEnergyUsageRepository
from ant_orchestrator.persistence.repositories.worker_run import SqliteWorkerRunRepository
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME


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


def _seed_task_and_run(client: TestClient, title: str = "Demo") -> dict:
    task_id = client.post("/tasks", json={"title": title}).json()["task_id"]
    run = client.post(f"/tasks/{task_id}/workflow-runs").json()
    return {"task_id": task_id, "run": run}


def _seed_worker_run_direct(workspace: Path, task_id: str) -> str:
    """Seed a WorkerRun and EnergyUsage directly via repositories; return worker_run_id."""
    db = Database(workspace / ANT_DIRNAME / DATABASE_FILENAME)
    now = UtcTimestamp(datetime.now(UTC))
    worker_run_id = str(uuid.uuid4())
    worker_run = WorkerRun(
        id=WorkerRunId(worker_run_id),
        task_id=TaskId(task_id),
        status=WorkerRunStatus.SUCCEEDED,
        created_at=now,
        started_at=now,
        finished_at=now,
    )
    SqliteWorkerRunRepository(db).add(worker_run)
    energy = EnergyUsage(
        id=EnergyUsageId(str(uuid.uuid4())),
        tokens_in=TokenCount(42),
        tokens_out=TokenCount(17),
        created_at=now,
        task_id=TaskId(task_id),
        worker_run_id=WorkerRunId(worker_run_id),
    )
    SqliteEnergyUsageRepository(db).append(energy)
    return worker_run_id


# --- GET /workflow-runs/{workflow_run_id} ---


def test_get_workflow_run_success(client: TestClient) -> None:
    info = _seed_task_and_run(client)
    wf_run_id = info["run"]["workflow_run_id"]
    resp = client.get(f"/workflow-runs/{wf_run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_run_id"] == wf_run_id
    assert data["task_id"] == info["task_id"]
    assert data["status"]
    assert "workflow_definition_version" in data
    assert "created_at" in data
    assert "updated_at" in data
    assert "cancel_requested" in data


def test_get_workflow_run_missing_404(client: TestClient) -> None:
    resp = client.get("/workflow-runs/no-such-run")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_get_workflow_run_no_graph_state_leak(client: TestClient) -> None:
    info = _seed_task_and_run(client)
    wf_run_id = info["run"]["workflow_run_id"]
    data = client.get(f"/workflow-runs/{wf_run_id}").json()
    assert "graph_state" not in data
    assert "checkpoint" not in data
    assert "thread_id" not in data


# --- GET /worker-runs/{worker_run_id} ---


def test_get_worker_run_success(client: TestClient, workspace: Path) -> None:
    task_id = client.post("/tasks", json={"title": "WorkerRun seed"}).json()["task_id"]
    wr_id = _seed_worker_run_direct(workspace, task_id)
    resp = client.get(f"/worker-runs/{wr_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["worker_run_id"] == wr_id
    assert data["task_id"] == task_id
    assert data["status"] == "succeeded"
    assert "created_at" in data
    assert "energy" in data
    assert "evidence" in data


def test_get_worker_run_missing_404(client: TestClient) -> None:
    resp = client.get("/worker-runs/no-such-run")
    assert resp.status_code == 404
    assert "error" in resp.json()


def test_get_worker_run_energy_visible(client: TestClient, workspace: Path) -> None:
    task_id = client.post("/tasks", json={"title": "Energy seed"}).json()["task_id"]
    wr_id = _seed_worker_run_direct(workspace, task_id)
    data = client.get(f"/worker-runs/{wr_id}").json()
    energy = data["energy"]
    assert energy["tokens_in"] == 42
    assert energy["tokens_out"] == 17
    assert energy["record_count"] == 1


def test_worker_run_id_not_interchangeable_with_workflow_run_id(client: TestClient) -> None:
    info = _seed_task_and_run(client)
    wf_run_id = info["run"]["workflow_run_id"]
    resp = client.get(f"/worker-runs/{wf_run_id}")
    assert resp.status_code == 404


# --- App isolation ---


def test_two_workspace_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runner = CliRunner()
    ws_a = tmp_path / "workspace_a"
    ws_b = tmp_path / "workspace_b"
    ws_a.mkdir()
    ws_b.mkdir()
    for ws in (ws_a, ws_b):
        monkeypatch.chdir(ws)
        runner.invoke(cli_app, ["init", "--path", str(ws)])

    with TestClient(create_app(ws_a)) as ca:
        with TestClient(create_app(ws_b)) as cb:
            id_a = ca.post("/tasks", json={"title": "Task A"}).json()["task_id"]
            assert ca.get(f"/tasks/{id_a}").status_code == 200
            assert cb.get(f"/tasks/{id_a}").status_code == 404


def test_no_module_level_app_object() -> None:
    import ast
    from pathlib import Path as _Path

    import ant_orchestrator

    main_file = _Path(ant_orchestrator.__file__).parent / "api" / "main.py"
    tree = ast.parse(main_file.read_text(encoding="utf-8"))
    # Only check module-level (tree.body), not function/class body.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "app":
                    raise AssertionError("module-level 'app' found in api/main.py")
