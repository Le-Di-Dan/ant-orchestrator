"""CLI delivery tests via Typer CliRunner (CP7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.main import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_creates_then_idempotent(project: Path) -> None:
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0
    assert "Initialised new Nest" in first.stdout
    second = runner.invoke(app, ["init"])
    assert second.exit_code == 0
    assert "already initialised" in second.stdout.lower()


def test_status_after_init(project: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 0
    assert "State: ready" in result.stdout


def test_status_without_nest_exits_3(project: Path) -> None:
    result = runner.invoke(app, ["status"])
    assert result.exit_code == 3


def test_config_show_after_init(project: Path) -> None:
    runner.invoke(app, ["init"])
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 0
    assert "version: 1" in result.stdout
    assert "project.name:" in result.stdout


def test_config_show_without_nest_exits_3(project: Path) -> None:
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == 3
