"""Phase 7 CP6 — ``ant memory search`` command.

Thin CLI adapter: validates presentation input, calls ``SearchMemory``, and renders
the result. No direct SQL, domain filtering, or business logic lives here.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from ant_orchestrator.cli import json_contract, render
from ant_orchestrator.cli.exit_codes import EXIT_USAGE, exit_code_for
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services
from ant_orchestrator.errors import AntError

_COMMAND = "memory_search"

_TYPE_OPTION = typer.Option(None, "--type", help="Filter by memory type.")
_SOURCE_OPTION = typer.Option(None, "--source", help="Exact case-sensitive source filter.")
_CONFIDENCE_OPTION = typer.Option(None, "--confidence", help="Filter by confidence level.")
_TAG_OPTION = typer.Option(None, "--tag", help="Tag filter (repeatable, ANY semantics).")
_TASK_OPTION = typer.Option(None, "--task", help="Filter by task ID.")
_LIMIT_OPTION = typer.Option(None, "--limit", help="Max records to return.")
_JSON_OPTION = typer.Option(False, "--json", help="Emit JSON document on stdout.")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: cwd).")


def _services(path: Path | None) -> WorkflowServices:
    return build_workflow_services(path if path is not None else Path.cwd())


def _fail(json_output: bool, exc: BaseException) -> NoReturn:
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload(_COMMAND, exc)))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for(exc))


def _usage_error(json_output: bool, msg: str) -> NoReturn:
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


def memory_search(
    memory_type: str | None = _TYPE_OPTION,
    source: str | None = _SOURCE_OPTION,
    confidence: str | None = _CONFIDENCE_OPTION,
    tag: list[str] | None = _TAG_OPTION,
    task_id: str | None = _TASK_OPTION,
    limit: int | None = _LIMIT_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Search memory records by type, source, confidence, tags, or task."""
    if limit is not None and limit <= 0:
        _usage_error(json_output, f"--limit must be positive, got {limit}")
    tags: tuple[str, ...] = tuple(tag) if tag else ()
    try:
        from ant_orchestrator.application.services.search_memory import MemorySearchRequest

        services = _services(path)
        request = MemorySearchRequest(
            memory_type=memory_type,
            task_id=task_id,
            source=source,
            confidence=confidence,
            tags=tags,
            include_deprecated=False,
            limit=limit,
        )
        result = services.search_memory.execute(request)
    except AntError as exc:
        _fail(json_output, exc)

    if json_output:
        typer.echo(json_contract.dumps(json_contract.memory_search_payload(result)))
        return
    for line in render.render_memory_results(result):
        typer.echo(line)


def register(app: typer.Typer) -> None:
    """Attach the ``memory`` sub-app with ``search`` command to the root app."""
    memory_app = typer.Typer(help="Memory operations.")
    memory_app.command("search")(memory_search)
    app.add_typer(memory_app, name="memory")
