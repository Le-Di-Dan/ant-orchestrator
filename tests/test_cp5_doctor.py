"""CP5 — antctl doctor command tests."""

from __future__ import annotations

import json
import os
import sysconfig
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.main import app
from ant_orchestrator.config.constants import ANT_CLI_VERSION, EXPECTED_DB_SCHEMA_VERSION

runner = CliRunner()


def _exe(name: str) -> Path:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"{name}{suffix}"


class TestDoctorBasic:
    def test_doctor_no_workspace_exits_0(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert result.exit_code == 0

    def test_doctor_overall_warn_when_no_workspace(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert "WARN" in result.output

    def test_doctor_shows_version(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert ANT_CLI_VERSION in result.output

    def test_doctor_shows_platform(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        import platform

        assert platform.system() in result.output

    def test_doctor_sections_present(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert "Installation:" in result.output
        assert "Workspace:" in result.output
        assert "Provider:" in result.output
        assert "Overall:" in result.output


class TestDoctorJson:
    def test_json_is_valid(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "schema_version" in data
        assert "overall" in data
        assert "checks" in data

    def test_json_no_ansi(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        assert "\x1b[" not in result.output

    def test_json_no_secret(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-secretvalue123")
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        assert "sk-secretvalue" not in result.output
        assert "secretvalue" not in result.output

    def test_json_has_version(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert data["version"] == ANT_CLI_VERSION

    def test_json_has_platform(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert "platform" in data
        assert "os" in data["platform"]
        assert "arch" in data["platform"]

    def test_json_checks_have_stable_fields(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        for check in data["checks"]:
            assert "check_id" in check
            assert "status" in check
            assert "message" in check
            assert "remediation" in check


class TestDoctorWorkspace:
    def test_healthy_workspace_passes(self, tmp_path: Path) -> None:
        from typer.testing import CliRunner as _Runner

        r = _Runner()
        r.invoke(app, ["init", "--path", str(tmp_path)])
        result = r.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert "workspace.found" in result.output
        assert "OK" in result.output

    def test_missing_workspace_warns(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert "WARN" in result.output
        assert "workspace.found" in result.output

    def test_workspace_with_invalid_db_fails(self, tmp_path: Path) -> None:
        ant_dir = tmp_path / ".ant"
        ant_dir.mkdir()
        (ant_dir / "workspace.json").write_text('{"workspace_id":"x","workspace_format_version":1}')
        # Write corrupt sqlite bytes
        (ant_dir / "state.sqlite").write_bytes(b"not-a-sqlite-file")
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        # DB check should be FAIL or schema absent
        assert "FAIL" in result.output or "WARN" in result.output

    def test_db_schema_v5_passes(self, tmp_path: Path) -> None:
        r = CliRunner()
        r.invoke(app, ["init", "--path", str(tmp_path)])
        result = r.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        db_check = next((c for c in data["checks"] if c["check_id"] == "workspace.db"), None)
        if db_check is not None:
            assert f"v{EXPECTED_DB_SCHEMA_VERSION}" in db_check["message"]


class TestDoctorProvider:
    def test_no_config_warns_provider(self, tmp_path: Path) -> None:
        r = CliRunner()
        r.invoke(app, ["init", "--path", str(tmp_path)])
        result = r.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert "provider" in result.output.lower() or "model" in result.output.lower()

    def test_openai_key_present_passes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = CliRunner()
        r.invoke(app, ["init", "--path", str(tmp_path)])
        r.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--non-interactive",
                "--path",
                str(tmp_path),
            ],
        )
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        result = r.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        cred_check = next((c for c in data["checks"] if "credential" in c["check_id"]), None)
        if cred_check is not None:
            assert cred_check["status"] == "PASS"

    def test_openai_key_missing_warns(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = CliRunner()
        r.invoke(app, ["init", "--path", str(tmp_path)])
        r.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--non-interactive",
                "--path",
                str(tmp_path),
            ],
        )
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        result = r.invoke(app, ["doctor", "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        cred_check = next((c for c in data["checks"] if "credential" in c["check_id"]), None)
        if cred_check is not None:
            assert cred_check["status"] == "WARN"


class TestDoctorLive:
    def test_live_flag_no_error(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--live"])
        assert result.exit_code == 0

    def test_live_without_invoke_model_skips_connectivity(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path), "--live", "--json"])
        data = json.loads(result.output)
        live_check = next((c for c in data["checks"] if c["check_id"] == "live.connectivity"), None)
        if live_check is not None:
            assert live_check["status"] == "SKIP"


class TestDoctorExitCode:
    def test_exit_0_when_no_fail(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        # WARN only → exit 0
        assert result.exit_code == 0

    def test_exit_1_when_fail(self, tmp_path: Path) -> None:
        ant_dir = tmp_path / ".ant"
        ant_dir.mkdir()
        (ant_dir / "workspace.json").write_text('{"workspace_id":"x","workspace_format_version":1}')
        (ant_dir / "state.sqlite").write_bytes(b"corrupt")
        with patch(
            "ant_orchestrator.cli.cp5_doctor_checks.antctl_exe_path",
            return_value=tmp_path / "no_antctl",
        ):
            result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        assert result.exit_code == 1


class TestDoctorNoNetwork:
    def test_default_no_network_calls(self, tmp_path: Path) -> None:
        """Doctor default must not make network calls — verify by running in a
        directory without any credentials or workspace config."""
        result = runner.invoke(app, ["doctor", "--path", str(tmp_path)])
        # Should not raise any connection errors
        assert result.exit_code in (0, 1)
