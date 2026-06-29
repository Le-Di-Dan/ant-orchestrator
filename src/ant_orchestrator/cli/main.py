"""Typer CLI for Ant-Orchestrator (Phase 1 delivery adapter).

Commands parse input, call an application service, render the result and map any
``AntError`` to a stable exit code. No domain/filesystem/SQLite logic lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from ant_orchestrator.application.models.outcomes import InitNestOutcome
from ant_orchestrator.cli import (
    cp5_configure,
    cp5_doctor,
    json_contract,
    phase4_commands,
    phase7_logs,
    phase7_memory,
    render,
)
from ant_orchestrator.cli import cp5_task_detail as _task_detail_module
from ant_orchestrator.cli.composition import build_services
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.cli.workflow_composition import build_workflow_services
from ant_orchestrator.config.constants import ANT_CLI_VERSION
from ant_orchestrator.errors import AntError

app = typer.Typer(help="Ant-Orchestrator CLI")
config_app = typer.Typer(help="Inspect resolved configuration.")
app.add_typer(config_app, name="config")

_STATUS_JSON_OPTION = typer.Option(False, "--json", help="Emit a single JSON document on stdout.")
_STATUS_PATH_OPTION = typer.Option(
    None, "--path", help="Project root (default: current directory)."
)

_INIT_MESSAGES = {
    InitNestOutcome.CREATED: "Initialised new Nest at {root}",
    InitNestOutcome.PROVISIONED: "Provisioned runtime database for Nest at {root}",
    InitNestOutcome.ALREADY_INITIALIZED: "Nest already initialised at {root}",
}

# Module-level singleton (avoids a function call in the argument default; B008).
_PATH_OPTION = typer.Option(None, help="Project root to initialise (default: cwd).")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(ANT_CLI_VERSION)
        raise typer.Exit()


@app.callback()
def root(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the CLI version and exit.",
    ),
) -> None:
    """Ant-Orchestrator CLI."""


def _fail(error: AntError) -> typer.Exit:
    typer.echo(str(error), err=True)
    return typer.Exit(exit_code_for(error))


@app.command()
def init(path: Path | None = _PATH_OPTION) -> None:
    """Create or provision the ``.ant/`` Nest for a project."""
    target = path if path is not None else Path.cwd()
    services = build_services()
    try:
        outcome = services.init_nest.init(target)
    except AntError as exc:
        raise _fail(exc) from exc
    typer.echo(_INIT_MESSAGES[outcome].format(root=target))


def _status_fail(json_output: bool, exc: BaseException) -> NoReturn:
    """Render a sanitized status error (JSON on stdout or text on stderr) and exit."""
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload("status", exc)))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for(exc))


@app.command()
def status(
    json_output: bool = _STATUS_JSON_OPTION,
    path: Path | None = _STATUS_PATH_OPTION,
) -> None:
    """Show the discovered Nest's readiness and its tasks (deterministic order)."""
    target = path if path is not None else Path.cwd()
    try:
        view = build_services().nest_status.status(target)
        report = build_workflow_services(target).task_status.report()
    except AntError as exc:
        _status_fail(json_output, exc)
    ready = view.state.value == "ready"
    if json_output:
        typer.echo(json_contract.dumps(json_contract.status_payload(report, workspace_ready=ready)))
        return
    typer.echo(f"Nest: {view.root}")
    typer.echo(f"State: {view.state.value}")
    typer.echo(f"Workspace format version: {view.workspace_format_version}")
    typer.echo(f"Schema version: {view.schema_version}")
    for line in render.render_status(report, workspace_ready=ready):
        typer.echo(line)


@config_app.command("show")
def config_show() -> None:
    """Show the resolved configuration for the discovered Nest."""
    services = build_services()
    try:
        view = services.show_config.show(Path.cwd())
    except AntError as exc:
        raise _fail(exc) from exc
    typer.echo(f"version: {view.config.version}")
    typer.echo(f"project.name: {view.config.project.name}")


phase4_commands.register(app)
phase7_logs.register(app)
phase7_memory.register(app)
cp5_doctor.register(app)
cp5_configure.register(app)

# Extend the existing ``task`` sub-typer (registered by phase4_commands) with
# the CP5 ``task show`` and ``task result`` commands.
_task_app = typer.Typer(help="Create and inspect tasks.")
_task_detail_module.register(_task_app)


def _register_cp5_task(root_app: typer.Typer) -> None:
    """Attach show/result to the task sub-typer already registered by phase4."""
    for group in root_app.registered_groups:
        if group.name == "task" and group.typer_instance is not None:
            _task_detail_module.register(group.typer_instance)
            return


_register_cp5_task(app)


def main() -> None:
    """Console-script entry point invoked by the ``ant`` and ``antctl`` commands."""
    app()
