"""Phase 8 CP5 — ``antctl doctor`` command.

Thin command adapter: collects check results from cp5_doctor_checks, renders
them (text or JSON) and maps overall status to the exit code.
"""

from __future__ import annotations

import platform
from pathlib import Path
from typing import Any, Final

import typer

from ant_orchestrator.cli import json_contract
from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_WARN,
    CheckResult,
    check_installation,
    overall_status,
)
from ant_orchestrator.cli.cp5_doctor_workspace import check_provider, check_workspace
from ant_orchestrator.cli.exit_codes import EXIT_OK, EXIT_UNEXPECTED
from ant_orchestrator.config.constants import ANT_CLI_VERSION, DOCTOR_JSON_SCHEMA_VERSION

_COMMAND: Final = "doctor"

_JSON_OPTION = typer.Option(False, "--json", help="Emit JSON on stdout (no ANSI).")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: cwd).")
_LIVE_OPTION = typer.Option(
    False, "--live", help="Probe endpoint connectivity (no model invocation)."
)
_INVOKE_OPTION = typer.Option(
    False,
    "--invoke-model",
    help="Allow a model invocation during --live check (may incur cost).",
)

_STATUS_ICON = {"PASS": "OK  ", "WARN": "WARN", "FAIL": "FAIL", "SKIP": "SKIP"}


def _render_checks(checks: list[CheckResult]) -> list[str]:
    lines: list[str] = []
    for c in checks:
        icon = _STATUS_ICON.get(c.status, c.status)
        lines.append(f"  [{icon}] {c.check_id}: {c.message}")
        if c.remediation and c.status in (STATUS_WARN, STATUS_FAIL):
            lines.append(f"         > {c.remediation}")
    return lines


def _checks_to_json(checks: list[CheckResult]) -> list[dict[str, Any]]:
    return [
        {
            "check_id": c.check_id,
            "status": c.status,
            "message": c.message,
            "remediation": c.remediation,
        }
        for c in checks
    ]


def _doctor_payload(all_checks: list[CheckResult], overall: str) -> dict[str, Any]:
    return {
        "schema_version": DOCTOR_JSON_SCHEMA_VERSION,
        "command": _COMMAND,
        "overall": overall,
        "version": ANT_CLI_VERSION,
        "platform": {"os": platform.system(), "arch": platform.machine()},
        "checks": _checks_to_json(all_checks),
    }


def doctor(
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
    live: bool = _LIVE_OPTION,
    invoke_model: bool = _INVOKE_OPTION,
) -> None:
    """Non-destructive environment health check."""
    search_root = path if path is not None else Path.cwd()

    install_checks = check_installation()
    workspace_checks = check_workspace(search_root)
    provider_checks = check_provider(search_root)

    if live and not invoke_model:
        live_note = CheckResult(
            check_id="live.connectivity",
            status="SKIP",
            message=(
                "--live endpoint probe not yet implemented (use --invoke-model for model test)"
            ),
        )
        provider_checks = list(provider_checks) + [live_note]
    elif invoke_model:
        typer.echo("WARNING: --invoke-model may incur API cost. Not implemented in CP5.", err=True)

    all_checks = install_checks + workspace_checks + provider_checks
    overall = overall_status(all_checks)

    if json_output:
        typer.echo(json_contract.dumps(_doctor_payload(all_checks, overall)))
        raise typer.Exit(EXIT_OK if overall != STATUS_FAIL else EXIT_UNEXPECTED)

    typer.echo(f"antctl doctor: {overall}")
    typer.echo("")
    typer.echo("Installation:")
    for line in _render_checks(install_checks):
        typer.echo(line)
    typer.echo("")
    typer.echo("Workspace:")
    for line in _render_checks(workspace_checks):
        typer.echo(line)
    typer.echo("")
    typer.echo("Provider:")
    for line in _render_checks(provider_checks):
        typer.echo(line)
    typer.echo("")
    typer.echo(f"Overall: {overall}")

    raise typer.Exit(EXIT_OK if overall != STATUS_FAIL else EXIT_UNEXPECTED)


def register(app: typer.Typer) -> None:
    """Attach the doctor command to the root Typer application."""
    app.command("doctor")(doctor)
