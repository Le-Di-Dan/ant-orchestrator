"""Phase 8 CP5 — ``antctl task show`` and ``antctl task result`` commands.

Both commands follow the thin-CLI contract: parse → service call → render → exit code.
No SQL, no domain logic, no artifact content.  ``--json`` output is ANSI-free and
sanitized (no raw provider output, no traceback, no secrets, no absolute paths).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final, NoReturn

import typer

from ant_orchestrator.application.models.execution_views import TaskDetailView
from ant_orchestrator.application.models.result_views import TaskResultView
from ant_orchestrator.cli import json_contract
from ant_orchestrator.cli.exit_codes import exit_code_for
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services
from ant_orchestrator.errors import AntError

_CMD_SHOW: Final = "task_show"
_CMD_RESULT: Final = "task_result"

_TASK_ID_ARG = typer.Argument(..., help="Task ID.")
_JSON_OPTION = typer.Option(False, "--json", help="Emit a single JSON document on stdout.")
_PATH_OPTION = typer.Option(None, "--path", help="Project root (default: cwd).")


def _services(path: Path | None) -> WorkflowServices:
    return build_workflow_services(path if path is not None else Path.cwd())


def _fail(command: str, json_output: bool, exc: BaseException) -> NoReturn:
    if json_output:
        typer.echo(json_contract.dumps(json_contract.error_payload(command, exc)))
    else:
        typer.echo(str(exc), err=True)
    raise typer.Exit(exit_code_for(exc))


# ---------------------------------------------------------------------------
# task show
# ---------------------------------------------------------------------------


def _task_show_payload(view: TaskDetailView) -> dict[str, Any]:
    payload = json_contract._base(_CMD_SHOW)
    payload["task_id"] = view.task_id
    payload["title"] = view.title
    payload["status"] = view.status
    payload["priority"] = view.priority
    payload["source"] = view.source
    payload["created_at"] = view.created_at
    payload["updated_at"] = view.updated_at
    if view.active_workflow_run is not None:
        run = view.active_workflow_run
        payload["workflow_run"] = {
            "workflow_run_id": run.workflow_run_id,
            "status": run.status,
            "cancel_requested": run.cancel_requested,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
        }
    else:
        payload["workflow_run"] = None
    payload["worker_run_count"] = len(view.worker_runs)
    payload["approval_count"] = len(view.approvals)
    payload["energy"] = {
        "tokens_in": view.energy_totals.tokens_in,
        "tokens_out": view.energy_totals.tokens_out,
        "record_count": view.energy_totals.record_count,
    }
    return payload


def _render_task_show(view: TaskDetailView) -> list[str]:
    lines = [
        f"Task: {view.task_id}",
        f"  Title:    {view.title}",
        f"  Status:   {view.status}",
        f"  Priority: {view.priority}",
        f"  Source:   {view.source}",
        f"  Created:  {view.created_at}",
        f"  Updated:  {view.updated_at}",
    ]
    if view.active_workflow_run is not None:
        run = view.active_workflow_run
        lines.append(f"  Workflow: {run.workflow_run_id} [{run.status}]")
        if run.cancel_requested:
            lines.append("    (cancel requested)")
    else:
        lines.append("  Workflow: none")
    lines.append(f"  Workers:  {len(view.worker_runs)} run(s)")
    pending = [a for a in view.approvals if a.status == "pending"]
    lines.append(
        f"  Approval: {len(view.approvals)} total"
        + (f", {len(pending)} pending" if pending else "")
    )
    lines.append(
        f"  Tokens:   {view.energy_totals.tokens_in} in / {view.energy_totals.tokens_out} out"
    )
    return lines


def task_show(
    task_id: str = _TASK_ID_ARG,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Show task details (identity, status, workflow run, approvals, energy)."""
    try:
        services = _services(path)
        view = services.get_task_detail.get(task_id)
    except AntError as exc:
        _fail(_CMD_SHOW, json_output, exc)

    if json_output:
        typer.echo(json_contract.dumps(_task_show_payload(view)))
    else:
        for line in _render_task_show(view):
            typer.echo(line)


# ---------------------------------------------------------------------------
# task result
# ---------------------------------------------------------------------------


def _artifact_entry(ref: Any) -> dict[str, Any]:
    return {
        "artifact_id": ref.artifact_id,
        "kind": ref.kind,
        "relative_path": ref.relative_path,
        "media_type": ref.media_type,
        "size_bytes": ref.size_bytes,
        "state": ref.state,
        "sha256": ref.sha256,
    }


def _task_result_payload(view: TaskResultView) -> dict[str, Any]:
    payload = json_contract._base(_CMD_RESULT)
    payload["task_id"] = view.task_id
    payload["result_id"] = view.result_id
    payload["workflow_run_id"] = view.workflow_run_id
    payload["outcome"] = view.outcome
    payload["summary"] = view.summary
    payload["finalized_at"] = view.finalized_at
    payload["result_version"] = view.result_version
    payload["artifact_refs"] = [_artifact_entry(a) for a in view.artifact_refs]
    if view.failure is not None:
        payload["failure"] = {
            "code": view.failure.code,
            "message": view.failure.message,
            "retryable": view.failure.retryable,
            "source": view.failure.source,
        }
    else:
        payload["failure"] = None
    return payload


def _render_task_result(view: TaskResultView) -> list[str]:
    lines = [
        f"Result for task: {view.task_id}",
        f"  Outcome:     {view.outcome}",
        f"  Summary:     {view.summary}",
        f"  Finalized:   {view.finalized_at}",
        f"  Version:     {view.result_version}",
    ]
    if view.failure is not None:
        lines.append(f"  Failure:     [{view.failure.code}] {view.failure.message}")
        lines.append(f"    Retryable: {view.failure.retryable}")
    if view.artifact_refs:
        lines.append(f"  Artifacts ({len(view.artifact_refs)}):")
        for ref in view.artifact_refs:
            lines.append(
                f"    {ref.kind}/{ref.state}: {ref.relative_path} ({ref.size_bytes} bytes)"
            )
    else:
        lines.append("  Artifacts:   none")
    return lines


def task_result(
    task_id: str = _TASK_ID_ARG,
    json_output: bool = _JSON_OPTION,
    path: Path | None = _PATH_OPTION,
) -> None:
    """Show the persisted result for a completed task."""
    try:
        services = _services(path)
        view = services.get_task_result.get(task_id)
    except AntError as exc:
        _fail(_CMD_RESULT, json_output, exc)

    if view is None:
        # Task exists but result is not yet finalized.
        msg = f"Result not yet available for task {task_id} (task may still be running)"
        if json_output:
            payload = json_contract._base(_CMD_RESULT)
            payload["task_id"] = task_id
            payload["ready"] = False
            payload["message"] = msg
            typer.echo(json_contract.dumps(payload))
        else:
            typer.echo(msg, err=True)
        raise typer.Exit(0)

    if json_output:
        typer.echo(json_contract.dumps(_task_result_payload(view)))
    else:
        for line in _render_task_result(view):
            typer.echo(line)


def register(task_app: typer.Typer) -> None:
    """Attach task show / task result to an existing ``task`` sub-Typer."""
    task_app.command("show")(task_show)
    task_app.command("result")(task_result)
