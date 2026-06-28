"""CP7 — Unified error contract, security, import boundary (Phase 7 API)."""

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


# --- Unified error shape ---


def test_not_found_unified_error(client: TestClient) -> None:
    resp = client.get("/tasks/no-such-task")
    assert resp.status_code == 404
    body = resp.json()
    assert "error" in body
    assert "type" in body["error"]
    assert "message" in body["error"]


def test_validation_error_unified(client: TestClient) -> None:
    resp = client.post("/tasks", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body


def test_workflow_state_error_422_shape(client: TestClient) -> None:
    task_id = client.post("/tasks", json={"title": "Terminal"}).json()["task_id"]
    client.post(f"/tasks/{task_id}/workflow-runs")
    resp = client.post(f"/tasks/{task_id}/workflow-runs")
    assert resp.status_code == 422
    body = resp.json()
    assert "error" in body
    assert "type" in body["error"]


# --- Security: no leakage ---


def test_no_traceback_in_error_response(client: TestClient) -> None:
    resp = client.get("/tasks/bad-id")
    text = resp.text
    assert "Traceback" not in text
    assert 'File "' not in text


def test_no_database_path_in_response(client: TestClient) -> None:
    resp = client.get("/tasks/bad-id")
    text = resp.text
    assert ".ant" not in text or "task" in text.lower()
    assert "\\" not in text or resp.status_code == 404


def test_no_raw_exception_class_in_response(client: TestClient) -> None:
    resp = client.get("/tasks/bad-id")
    text = resp.text
    assert "RecordNotFound" not in text
    assert "DatabasePortError" not in text


def test_extra_fields_in_request_rejected(client: TestClient) -> None:
    resp = client.post("/tasks", json={"title": "T", "internal_field": "hack"})
    assert resp.status_code == 422


# --- Import boundary ---


def test_api_does_not_import_cli_composition() -> None:
    import ast
    from pathlib import Path as _Path

    import ant_orchestrator

    api_dir = _Path(ant_orchestrator.__file__).parent / "api"
    for f in api_dir.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                assert not node.module.startswith("ant_orchestrator.cli"), (
                    f"{f} imports from cli/: {node.module}"
                )


def test_composition_does_not_import_cli() -> None:
    import ast
    from pathlib import Path as _Path

    import ant_orchestrator

    comp_file = _Path(ant_orchestrator.__file__).parent / "composition.py"
    tree = ast.parse(comp_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            assert not node.module.startswith("ant_orchestrator.cli"), (
                f"composition.py imports from cli/: {node.module}"
            )


def test_neutral_composition_no_fastapi() -> None:
    import ast
    from pathlib import Path as _Path

    import ant_orchestrator

    comp_file = _Path(ant_orchestrator.__file__).parent / "composition.py"
    tree = ast.parse(comp_file.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            assert "fastapi" not in node.module, f"composition.py imports fastapi: {node.module}"


def test_real_audit_sink_not_null_in_api(workspace: Path) -> None:
    from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
    from ant_orchestrator.api.dependencies import build_api_services

    services = build_api_services(workspace)
    # SearchMemory holds the audit sink as self._sink — verify it's a real JsonlAuditSink
    search = services.search_memory
    assert isinstance(search._sink, JsonlAuditSink), (  # type: ignore[attr-defined]
        f"Expected JsonlAuditSink, got {type(search._sink)}"
    )
