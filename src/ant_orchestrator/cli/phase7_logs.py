"""Phase 7 CP6 — ``ant logs`` command.

Thin CLI adapter: validates presentation input, calls ``GetTaskLogs``, and renders
the result. No direct SQL, JSONL I/O, or business logic lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from ant_orchestrator.cli import json_contract, render
from ant_orchestrator.cli.exit_codes import EXIT_USAGE, exit_code_for
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT
from ant_orchestrator.errors import AntError

_TASK_OPTION = typer.Option(None, "--task", help="Filter by task ID.")
_LIMIT_OPTION = typer.Option(None, "--limit", help="Max entries to return.")
_SINCE_OPTION = typer.Option(None, "--since", help="ISO 8601 UTC timestamp (inclusive).")
_JSON_OPTION = typer.Option(False, "--json", help="Emit a single JSON document on stdout.")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: current directory).")

_COMMAND = "logs"


def _services(path: Path | None) -> WorkflowServices:
    return build_workflow_services(path if path is not None else Path.cwd())


def _fail(json_output: bool, exc: BaseException) -> NoReturn:
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload(_COMMAND, exc)))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for(exc))


def logs(
    task_id: str | None = _TASK_OPTION,
    limit: int | None = _LIMIT_OPTION,
    since: str | None = _SINCE_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Show bounded audit log entries, newest first."""
    if limit is not None and limit <= 0:
        msg = f"--limit must be positive, got {limit}"
        if json_output:
            typer.echo(
                json_contract.dumps(
                    {
                        "schema_version": 1,
                        "command": _COMMAND,
                        "error": {"type": "UsageError", "message": msg},
                    }
                )
            )
        else:
            typer.echo(msg, err=True)
        raise typer.Exit(EXIT_USAGE)
    try:
        services = _services(path)
        page = services.get_task_logs.query(task_id=task_id, limit=limit, since=since)
    except AntError as exc:
        _fail(json_output, exc)

    resolved_limit = limit if limit is not None else LOG_DEFAULT_LIMIT
    if json_output:
        payload = json_contract.logs_payload(page, resolved_limit=resolved_limit)
        typer.echo(json_contract.dumps(payload))
        return
    for line in render.render_logs(page):
        typer.echo(line)


def register(app: typer.Typer) -> None:
    """Attach ``ant logs`` to the root Typer application."""
    app.command("logs")(logs)
