"""Typer CLI for Ant-Orchestrator (Phase 1 delivery adapter).

Commands parse input, call an application service, render the result and map any
``AntError`` to a stable exit code. No domain/filesystem/SQLite logic lives here.
"""

from __future__ import annotations

from pathlib import Path

import typer

from ant_orchestrator.application.models.outcomes import InitNestOutcome
from ant_orchestrator.cli.composition import Services, build_services
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.errors import AntError

app = typer.Typer(help="Ant-Orchestrator CLI")
config_app = typer.Typer(help="Inspect resolved configuration.")
app.add_typer(config_app, name="config")

_INIT_MESSAGES = {
    InitNestOutcome.CREATED: "Initialised new Nest at {root}",
    InitNestOutcome.PROVISIONED: "Provisioned runtime database for Nest at {root}",
    InitNestOutcome.ALREADY_INITIALIZED: "Nest already initialised at {root}",
}

# Module-level singleton (avoids a function call in the argument default; B008).
_PATH_OPTION = typer.Option(None, help="Project root to initialise (default: cwd).")


@app.callback()
def root() -> None:
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


@app.command()
def status() -> None:
    """Show the state of the discovered Nest."""
    services: Services = build_services()
    try:
        view = services.nest_status.status(Path.cwd())
    except AntError as exc:
        raise _fail(exc) from exc
    typer.echo(f"Nest: {view.root}")
    typer.echo(f"State: {view.state.value}")
    typer.echo(f"Workspace format version: {view.workspace_format_version}")
    typer.echo(f"Schema version: {view.schema_version}")


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


def main() -> None:
    """Console-script entry point invoked by the ``ant`` command."""
    app()
