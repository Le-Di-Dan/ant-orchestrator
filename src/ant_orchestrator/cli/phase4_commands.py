"""Phase 4 workflow CLI commands (PHASE_4_PLAN CP7).

Each command follows the same thin shape: parse arguments → resolve workspace → build
the composition → call one application use case → render the result → map any typed
error to an exit code. No lifecycle/SQL/LangGraph/CAS logic lives here; commands only
call services. ``--json`` is opt-in and, when set, stdout carries a single JSON document
(success or sanitized error) stamped with ``schema_version``.
"""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from ant_orchestrator.cli import json_contract, render
from ant_orchestrator.cli.composition_production import build_production_workflow_services
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.cli.json_contract import JsonObject
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services
from ant_orchestrator.config.constants import MAX_REJECT_REASON_CHARS
from ant_orchestrator.core.domain.enums import ActorSource, TaskPriority
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.errors import AntError

# Module-level option/argument singletons (avoid a function call in a default; B008).
_TASK_ID_ARG = typer.Argument(..., help="Task id.")
_TITLE_OPTION = typer.Option(..., "--title", help="Task title (non-empty).")
_PRIORITY_OPTION = typer.Option(None, "--priority", help="Task priority: low|normal|high.")
_REASON_OPTION = typer.Option(..., "--reason", help="Rejection reason (required).")
_BY_OPTION = typer.Option(None, "--by", help="Optional actor label (not a verified identity).")
_JSON_OPTION = typer.Option(False, "--json", help="Emit a single JSON document on stdout.")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: current directory).")


def _services(path: Path | None) -> WorkflowServices:
    """Neutral composition — no LLM needed (task create/status/approve/reject/cancel)."""
    return build_workflow_services(path if path is not None else Path.cwd())


def _run_services(path: Path | None) -> WorkflowServices:
    """Production composition for ``ant run`` — requires queen + local provider config.

    Always production: there is NO environment switch or user-selectable config that
    can substitute the deterministic stub here. Deterministic verification lives in the
    isolated ``antctl self-test`` command, never in this production path.
    """
    resolved = path if path is not None else Path.cwd()
    return build_production_workflow_services(resolved)


def _fail(command: str, json_output: bool, exc: BaseException) -> NoReturn:
    """Render a sanitized error (JSON on stdout or text on stderr) and exit."""
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload(command, exc)))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for(exc))


def _emit(json_output: bool, payload: JsonObject, lines: list[str]) -> None:
    if json_output:
        typer.echo(json_contract.dumps(payload))
    else:
        for line in lines:
            typer.echo(line)


def _sanitize_reason(raw: str) -> str:
    """Strip control characters, collapse to non-empty, and bound the length."""
    cleaned = "".join(ch for ch in raw if ch == " " or ch.isprintable()).strip()
    if not cleaned:
        raise InvariantViolation("reject reason must be non-empty")
    return cleaned[:MAX_REJECT_REASON_CHARS]


def task_create(
    title: str = _TITLE_OPTION,
    priority: str | None = _PRIORITY_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Create exactly one task in the CREATED state (no workflow run)."""
    command = "task_create"
    try:
        services = _services(path)
        prio = TaskPriority.parse(priority) if priority else TaskPriority.NORMAL
        task = services.create_task.create(title=title, priority=prio)
    except AntError as exc:
        _fail(command, json_output, exc)
    _emit(json_output, json_contract.create_payload(task), render.render_create(task))


def run(
    task_id: str = _TASK_ID_ARG,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Start or re-enter the workflow for a task."""
    command = "run"
    try:
        services = _run_services(path)
        outcome = services.run_workflow.execute(task_id)
    except AntError as exc:
        _fail(command, json_output, exc)
    _emit(
        json_output,
        json_contract.outcome_payload(command, task_id, outcome),
        render.render_outcome(task_id, outcome),
    )


def approve(
    task_id: str = _TASK_ID_ARG,
    by: str | None = _BY_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Approve the pending gate for a task (actor source: local CLI).

    Uses the *production* composition: approving auto-resumes the workflow and the
    approved continuation executes a real worker. Routing this through the neutral
    composition would silently run that work on ``DeterministicStubAdapter`` and
    fabricate a completed result, so approve must fail-closed on missing provider
    config exactly like ``run``.
    """
    command = "approve"
    try:
        services = _run_services(path)
        outcome = services.resolve_approval.approve(
            task_id, actor_source=ActorSource.LOCAL_CLI, actor_label=by
        )
    except AntError as exc:
        _fail(command, json_output, exc)
    _emit(
        json_output,
        json_contract.outcome_payload(command, task_id, outcome),
        render.render_outcome(task_id, outcome),
    )


def reject(
    task_id: str = _TASK_ID_ARG,
    reason: str = _REASON_OPTION,
    by: str | None = _BY_OPTION,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Reject the pending gate for a task with a required, sanitized reason.

    Uses the *neutral* composition on purpose: a rejected resume routes the graph
    straight to its terminal rejected node and never invokes a worker, so reject must
    keep working without provider config. The default stub worker is therefore wired
    but never executed (asserted by ``test_reject_pending_rejects_without_worker``).
    """
    command = "reject"
    try:
        services = _services(path)
        clean_reason = _sanitize_reason(reason)
        outcome = services.resolve_approval.reject(
            task_id,
            reason=clean_reason,
            actor_source=ActorSource.LOCAL_CLI,
            actor_label=by,
        )
    except AntError as exc:
        _fail(command, json_output, exc)
    _emit(
        json_output,
        json_contract.outcome_payload(command, task_id, outcome),
        render.render_outcome(task_id, outcome),
    )


def cancel(
    task_id: str = _TASK_ID_ARG,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Cancel a task: CREATED/AWAITING -> CANCELLED, RUNNING -> CANCEL_REQUESTED."""
    command = "cancel"
    try:
        services = _services(path)
        outcome = services.cancel_task.cancel(task_id)
    except AntError as exc:
        _fail(command, json_output, exc)
    _emit(
        json_output,
        json_contract.outcome_payload(command, task_id, outcome),
        render.render_outcome(task_id, outcome),
    )


def register(app: typer.Typer) -> None:
    """Attach the Phase 4 commands to the root Typer application."""
    task_app = typer.Typer(help="Create and inspect tasks.")
    task_app.command("create")(task_create)
    app.add_typer(task_app, name="task")
    app.command("run")(run)
    app.command("approve")(approve)
    app.command("reject")(reject)
    app.command("cancel")(cancel)
