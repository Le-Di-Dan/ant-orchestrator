"""Human-readable text rendering for the Phase 4 CLI commands (PHASE_4_PLAN CP7).

Each function returns the lines to print (no I/O here) so rendering is unit-testable.
Output is sanitized: only ids and enum-derived status strings are shown — never a raw
checkpoint channel, ``request_json`` payload, secret or stack trace.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage
from ant_orchestrator.application.services.search_memory import MemorySearchResult
from ant_orchestrator.application.services.task_status import TaskStatusReport
from ant_orchestrator.application.services.workflow_support import WorkflowOutcome
from ant_orchestrator.core.domain.entities import Task


def render_create(task: Task) -> list[str]:
    """Lines for ``ant task create``: task id and status (minimum required)."""
    return [
        f"Task: {task.id.value}",
        f"Status: {task.status.value}",
        f"Priority: {task.priority.value}",
    ]


def render_outcome(task_id: str, outcome: WorkflowOutcome) -> list[str]:
    """Lines for run/approve/reject/cancel: id, run id, status, pending gate."""
    lines = [f"Task: {task_id}"]
    if outcome.run_id:
        lines.append(f"Workflow run: {outcome.run_id}")
    lines.append(f"Status: {outcome.status}")
    if outcome.approval_id is not None:
        lines.append(f"Pending approval: {outcome.approval_id}")
    return lines


def render_logs(page: AuditLogPage) -> list[str]:
    """Lines for ``ant logs``: one block per event, newest first."""
    if not page.events:
        return []
    lines: list[str] = []
    for event in page.events:
        task_id = event.detail.get("task_id") or "-"
        lines.append(
            f"[{event.created_at.to_iso()}] {event.event_type.value}"
            f" | task={task_id} | corr={str(event.correlation_id)[:8]}"
        )
    return lines


def render_memory_results(result: MemorySearchResult) -> list[str]:
    """Lines for ``ant memory search``: one block per record, no summary/content."""
    if not result.records:
        return []
    lines: list[str] = []
    for record in result.records:
        conf = record.confidence.value if record.confidence is not None else "-"
        src = record.source or "-"
        tags_str = ", ".join(record.tags) if record.tags else "-"
        lines.append(f"- {record.id.value} [{record.type.value}] {record.title!r}")
        lines.append(f"  confidence={conf} source={src}")
        lines.append(f"  created={record.created_at.to_iso()} tags={tags_str}")
    return lines


def render_status(report: TaskStatusReport, *, workspace_ready: bool) -> list[str]:
    """Lines for ``ant status``: workspace readiness then one block per task."""
    readiness = "ready" if workspace_ready else "not ready"
    lines = [f"Workspace: {readiness}"]
    if report.truncated:
        lines.append(f"Tasks: showing {len(report.rows)} of {report.total} (most recent)")
    else:
        lines.append(f"Tasks: {report.total}")
    for row in report.rows:
        lines.append(f"- {row.task_id} [{row.status}] priority={row.priority}")
        if row.workflow_run_id is not None:
            lines.append(f"    run {row.workflow_run_id} ({row.run_status})")
        if row.pending_gate_type is not None:
            lines.append(f"    pending gate: {row.pending_gate_type}")
        if row.cancel_requested:
            lines.append("    cancel requested")
    return lines
