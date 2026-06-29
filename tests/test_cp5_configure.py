"""CP5 — antctl configure command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.main import app
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.config.resolver import ConfigResolver

runner = CliRunner()


def _init(tmp_path: Path) -> None:
    runner.invoke(app, ["init", "--path", str(tmp_path)])


def _configure_non_interactive(
    tmp_path: Path,
    provider: str = "openai",
    model: str = "gpt-4o",
    role: str = "queen",
    extra: list[str] | None = None,
) -> object:
    args = [
        "configure",
        "--provider",
        provider,
        "--model",
        model,
        "--role",
        role,
        "--non-interactive",
        "--path",
        str(tmp_path),
    ]
    if extra:
        args.extend(extra)
    return runner.invoke(app, args)


class TestConfigureNonInteractive:
    def test_writes_config_yaml(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = _configure_non_interactive(tmp_path)
        assert result.exit_code == 0
        config_path = tmp_path / ".ant" / "config.yaml"
        assert config_path.exists()

    def test_config_has_correct_provider_model(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _configure_non_interactive(tmp_path, provider="openai", model="gpt-4o-mini")
        config_path = tmp_path / ".ant" / "config.yaml"
        data = load_document(config_path)
        config = ConfigResolver().resolve(file_data=data, env={})
        assert config.models.queen is not None
        assert config.models.queen.provider == "openai"
        assert config.models.queen.model == "gpt-4o-mini"

    def test_local_role_writes_local_endpoint(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _configure_non_interactive(
            tmp_path,
            provider="ollama",
            model="llama3",
            role="local",
            extra=["--base-url", "http://localhost:11434"],
        )
        config_path = tmp_path / ".ant" / "config.yaml"
        data = load_document(config_path)
        config = ConfigResolver().resolve(file_data=data, env={})
        assert config.models.local is not None
        assert config.models.local.provider == "ollama"
        assert config.models.local.model == "llama3"

    def test_missing_provider_fails(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            ["configure", "--model", "gpt-4o", "--non-interactive", "--path", str(tmp_path)],
        )
        assert result.exit_code != 0

    def test_missing_model_fails(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--non-interactive",
                "--path",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_invalid_provider_fails(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = _configure_non_interactive(tmp_path, provider="fake-provider")
        assert result.exit_code != 0

    def test_invalid_role_fails(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--role",
                "unknown",
                "--non-interactive",
                "--path",
                str(tmp_path),
            ],
        )
        assert result.exit_code != 0

    def test_no_workspace_fails(self, tmp_path: Path) -> None:
        result = _configure_non_interactive(tmp_path)
        assert result.exit_code != 0

    def test_secret_not_in_yaml(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENAI_API_KEY", "sk-super-secret-value")
        _init(tmp_path)
        _configure_non_interactive(tmp_path)
        config_path = tmp_path / ".ant" / "config.yaml"
        text = config_path.read_text()
        assert "sk-super-secret-value" not in text
        assert "OPENAI_API_KEY" not in text


class TestConfigureAtomicWrite:
    def test_old_config_preserved_on_write_failure(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _configure_non_interactive(tmp_path, provider="openai", model="gpt-4o")
        config_path = tmp_path / ".ant" / "config.yaml"
        original_text = config_path.read_text()

        # Simulate write failure by making the directory read-only is hard on
        # Windows; instead patch _write_atomic to raise.
        import ant_orchestrator.cli.cp5_configure as _mod

        original_write = _mod._write_atomic

        def _fail_write(p: Path, c: object) -> None:
            raise OSError("simulated write failure")

        _mod._write_atomic = _fail_write  # type: ignore[assignment]
        try:
            _configure_non_interactive(tmp_path, provider="ollama", model="llama3")
        finally:
            _mod._write_atomic = original_write

        # Config must be unchanged.
        assert config_path.read_text() == original_text

    def test_written_config_is_deterministic_yaml(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _configure_non_interactive(tmp_path, provider="openai", model="gpt-4o")
        config_path = tmp_path / ".ant" / "config.yaml"
        text1 = config_path.read_text()
        _configure_non_interactive(tmp_path, provider="openai", model="gpt-4o")
        text2 = config_path.read_text()
        assert text1 == text2


class TestConfigureJson:
    def test_json_output_non_interactive(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--non-interactive",
                "--json",
                "--path",
                str(tmp_path),
            ],
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["provider"] == "openai"
        assert data["model"] == "gpt-4o"
        assert "config_path" in data

    def test_json_no_prompt_non_interactive(self, tmp_path: Path) -> None:
        _init(tmp_path)
        result = runner.invoke(
            app,
            [
                "configure",
                "--provider",
                "openai",
                "--model",
                "gpt-4o",
                "--non-interactive",
                "--json",
                "--path",
                str(tmp_path),
            ],
        )
        # Should not block or prompt
        assert result.exit_code == 0


class TestConfigureReload:
    def test_configure_updates_are_readable_by_show_config(self, tmp_path: Path) -> None:
        _init(tmp_path)
        _configure_non_interactive(tmp_path, provider="openai", model="gpt-4o-mini")
        # Read via config loader to verify composition would pick up the change.
        config_path = tmp_path / ".ant" / "config.yaml"
        data = load_document(config_path)
        config = ConfigResolver().resolve(file_data=data, env={})
        assert config.models.queen is not None
        assert config.models.queen.model == "gpt-4o-mini"
