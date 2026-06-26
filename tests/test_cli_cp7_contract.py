"""CP7 — exit-code mapping, error contract and CLI architecture boundary tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ant_orchestrator.application.errors import (
    ApprovalRuleViolation,
    ApprovalStateConflict,
    CheckpointRecoveryError,
    WorkflowStateError,
)
from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.application.ports.workspace import NestNotFound
from ant_orchestrator.cli import json_contract, phase4_commands, render
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.errors import InvariantViolation
from tests.support.cli_cp7 import cli, nest  # noqa: F401  (nest is a fixture)


def test_exit_code_mapping() -> None:
    assert exit_code_for(CheckpointRecoveryError("x")) == 4
    assert exit_code_for(ApprovalRuleViolation("x")) == 6
    assert exit_code_for(ApprovalStateConflict("x")) == 5
    assert exit_code_for(WorkflowStateError("x")) == 5
    assert exit_code_for(InvariantViolation("x")) == 2
    assert exit_code_for(NestNotFound("x")) == 3
    assert exit_code_for(RecordNotFound("x")) == 4
    assert exit_code_for(RuntimeError("x")) == 1


def test_usage_error_missing_argument(nest: Path) -> None:  # noqa: F811
    assert cli.invoke(app, ["run"]).exit_code == 2
    assert cli.invoke(app, ["task", "create"]).exit_code == 2


def test_workspace_missing_exits_3(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no `ant init` → no Nest
    result = cli.invoke(app, ["run", "T1", "--json"])
    assert result.exit_code == 3
    assert json.loads(result.stdout)["error"]["type"] == "NestNotFound"


def test_approval_rule_violation_exits_6(nest: Path) -> None:  # noqa: F811
    created = cli.invoke(app, ["task", "create", "--title", "demo", "--json"])
    task_id = json.loads(created.stdout)["task_id"]
    # CREATED task has no pending approval → approving it violates the gate rule.
    result = cli.invoke(app, ["approve", task_id, "--json"])
    assert result.exit_code == 6
    assert json.loads(result.stdout)["error"]["type"] == "ApprovalRuleViolation"


def test_json_error_shape_is_sanitized(nest: Path) -> None:  # noqa: F811
    result = cli.invoke(app, ["run", "missing", "--json"])
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == 1
    assert set(payload["error"].keys()) == {"type", "message"}


@pytest.mark.parametrize("module", [phase4_commands, render, json_contract])
def test_cli_modules_have_no_sql_or_langgraph(module: object) -> None:
    """CLI command/render/json modules must not reach into SQL or LangGraph directly."""
    source = Path(module.__file__).read_text(encoding="utf-8")  # type: ignore[attr-defined]
    for forbidden in ("sqlite3", "langgraph", "SqliteUnitOfWork", "persistence.repositories"):
        assert forbidden not in source, f"{module.__name__} must not reference {forbidden}"
