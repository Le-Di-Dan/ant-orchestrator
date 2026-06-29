"""Phase 8 CP5 — ``antctl configure`` command.

Interactive and non-interactive configuration of AI provider endpoints.
Writes atomically to .ant/config.yaml; never stores secrets; never dumps env.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Final, NoReturn

import typer
import yaml

from ant_orchestrator.cli import json_contract
from ant_orchestrator.cli.exit_codes import EXIT_USAGE, EXIT_WORKSPACE
from ant_orchestrator.config.constants import (
    CONFIG_DOCUMENT_VERSION,
    CONFIG_FILENAME,
    CONFIGURE_SUPPORTED_PROVIDERS,
)
from ant_orchestrator.config.errors import ConfigError
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.config.models import (
    ModelEndpointConfig,
    ModelsConfig,
    ProjectConfig,
    ResolvedConfig,
)
from ant_orchestrator.config.resolver import ConfigResolver
from ant_orchestrator.errors import AntError
from ant_orchestrator.workspace.discovery import find_nest
from ant_orchestrator.workspace.layout import ANT_DIRNAME

_COMMAND: Final = "configure"

_PROVIDER_OPTION = typer.Option(None, "--provider", help="Provider: openai or ollama.")
_MODEL_OPTION = typer.Option(None, "--model", help="Model name.")
_ROLE_OPTION = typer.Option("queen", "--role", help="Endpoint role: queen or local.")
_BASE_URL_OPTION = typer.Option(None, "--base-url", help="Base URL (for ollama).")
_TIMEOUT_OPTION = typer.Option(None, "--timeout-seconds", help="Timeout in seconds.")
_NON_INTERACTIVE_OPTION = typer.Option(
    False, "--non-interactive", help="Skip prompts; fail if required flags are missing."
)
_JSON_OPTION = typer.Option(False, "--json", help="Emit JSON on stdout.")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: cwd).")

_SUPPORTED_ROLES: Final = frozenset({"queen", "local"})


def _fail(json_output: bool, msg: str, code: int = EXIT_USAGE) -> NoReturn:
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload(_COMMAND, ValueError(msg))))
    else:
        typer.echo(msg, err=True)
    raise typer.Exit(code)


def _resolve_root(path: Path | None) -> Path:
    search = path if path is not None else Path.cwd()
    root = find_nest(search)
    if root is None:
        raise AntError(f"No .ant/ workspace found from {search}. Run: antctl init")
    return root


def _load_existing(config_path: Path) -> ResolvedConfig:
    """Load existing config or return defaults."""
    try:
        file_data = load_document(config_path)
        return ConfigResolver().resolve(file_data=file_data, env={})
    except ConfigError:
        return ResolvedConfig(
            version=CONFIG_DOCUMENT_VERSION,
            project=ProjectConfig(name="unnamed"),
        )


def _write_atomic(config_path: Path, config: ResolvedConfig) -> None:
    """Write config YAML atomically via a temp file in the same directory."""
    data: dict[str, object] = {
        "version": config.version,
        "project": {"name": config.project.name},
    }
    models_data: dict[str, object] = {}
    if config.models.queen is not None:
        models_data["queen"] = _endpoint_dict(config.models.queen)
    if config.models.local is not None:
        models_data["local"] = _endpoint_dict(config.models.local)
    if models_data:
        data["models"] = models_data

    text = yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
    # Atomic replace: write to temp, then rename (same dir → same filesystem).
    dir_ = config_path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp-config-", suffix=".yaml", dir=dir_)
    try:
        import os as _os

        _os.write(fd, text.encode("utf-8"))
        _os.fsync(fd)
        _os.close(fd)
        fd = -1
        Path(tmp_path).replace(config_path)
    except Exception:
        if fd >= 0:
            import os as _os

            _os.close(fd)
        Path(tmp_path).unlink(missing_ok=True)
        raise


def _endpoint_dict(ep: ModelEndpointConfig) -> dict[str, object]:
    d: dict[str, object] = {"provider": ep.provider, "model": ep.model}
    if ep.base_url is not None:
        d["base_url"] = ep.base_url
    if ep.timeout_seconds is not None:
        d["timeout_seconds"] = ep.timeout_seconds
    return d


def _validate_provider(provider: str, json_output: bool) -> None:
    if provider not in CONFIGURE_SUPPORTED_PROVIDERS:
        _fail(
            json_output,
            f"Unsupported provider '{provider}'. "
            f"Supported: {sorted(CONFIGURE_SUPPORTED_PROVIDERS)}",
        )


def _validate_role(role: str, json_output: bool) -> None:
    if role not in _SUPPORTED_ROLES:
        _fail(
            json_output,
            f"Unknown role '{role}'. Supported: {sorted(_SUPPORTED_ROLES)}",
        )


def _prompt_provider() -> str:
    providers = sorted(CONFIGURE_SUPPORTED_PROVIDERS)
    typer.echo(f"Supported providers: {', '.join(providers)}")
    result: str = typer.prompt("Provider", default="openai")
    return result


def _prompt_model(provider: str) -> str:
    default = "gpt-4o" if provider == "openai" else "llama3"
    result: str = typer.prompt("Model", default=default)
    return result


def _build_endpoint(
    provider: str,
    model: str,
    base_url: str | None,
    timeout_seconds: float | None,
) -> ModelEndpointConfig:
    return ModelEndpointConfig(
        provider=provider,
        model=model,
        base_url=base_url,
        timeout_seconds=timeout_seconds,
    )


def _apply_endpoint(
    existing: ResolvedConfig,
    role: str,
    endpoint: ModelEndpointConfig,
) -> ResolvedConfig:
    queen = existing.models.queen
    local = existing.models.local
    if role == "queen":
        queen = endpoint
    else:
        local = endpoint
    return ResolvedConfig(
        version=existing.version,
        project=existing.project,
        models=ModelsConfig(queen=queen, local=local),
    )


def configure(
    provider: str | None = _PROVIDER_OPTION,
    model: str | None = _MODEL_OPTION,
    role: str = _ROLE_OPTION,
    base_url: str | None = _BASE_URL_OPTION,
    timeout_seconds: float | None = _TIMEOUT_OPTION,
    non_interactive: bool = _NON_INTERACTIVE_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Configure AI provider endpoints for the workspace."""
    _validate_role(role, json_output)

    try:
        root = _resolve_root(path)
    except AntError as exc:
        _fail(json_output, str(exc), EXIT_WORKSPACE)

    config_path = root / ANT_DIRNAME / CONFIG_FILENAME
    existing = _load_existing(config_path)

    if non_interactive:
        if provider is None:
            _fail(json_output, "--provider is required in --non-interactive mode")
        if model is None:
            _fail(json_output, "--model is required in --non-interactive mode")
        _validate_provider(provider, json_output)
    else:
        # Interactive prompts only when flags are absent.
        if provider is None:
            provider = _prompt_provider()
        _validate_provider(provider, json_output)
        if model is None:
            model = _prompt_model(provider)
        if base_url is None and provider == "ollama":
            base_url = typer.prompt("Base URL", default="http://localhost:11434")

    endpoint = _build_endpoint(provider, model, base_url, timeout_seconds)

    # Validate the combined config before writing.
    new_config = _apply_endpoint(existing, role, endpoint)
    try:
        raw: dict[str, object] = {"version": new_config.version}
        ConfigResolver().resolve(file_data=raw, env={})
    except ConfigError as exc:
        _fail(json_output, f"Config validation failed: {exc}")

    try:
        _write_atomic(config_path, new_config)
    except OSError as exc:
        _fail(json_output, f"Failed to write config: {exc}", EXIT_WORKSPACE)

    if json_output:
        payload = json_contract._base(_COMMAND)
        payload["role"] = role
        payload["provider"] = provider
        payload["model"] = model
        payload["config_path"] = str(config_path)
        typer.echo(json_contract.dumps(payload))
    else:
        typer.echo(f"Configured {role}: provider={provider} model={model}")
        typer.echo(f"Written to: {config_path}")


def register(app: typer.Typer) -> None:
    """Attach the configure command to the root Typer application."""
    app.command("configure")(configure)
