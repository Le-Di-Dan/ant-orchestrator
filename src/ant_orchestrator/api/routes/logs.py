"""API route: GET /logs."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool

from ant_orchestrator.api.schemas import LogEntrySchema, LogsResponse
from ant_orchestrator.application.ports.audit import AuditEvent
from ant_orchestrator.composition import WorkflowServices
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT

router = APIRouter()

_LIMIT_QUERY = Query(None, description="Max entries to return (default: LOG_DEFAULT_LIMIT).")
_TASK_QUERY = Query(None, description="Filter by task ID.")
_SINCE_QUERY = Query(None, description="ISO 8601 UTC timestamp (inclusive).")


def _get_services(request: Request) -> WorkflowServices:
    return request.app.state.services  # type: ignore[no-any-return]


def _log_entry_schema(event: AuditEvent) -> LogEntrySchema:
    return LogEntrySchema(
        event_type=event.event_type.value,
        created_at=event.created_at.to_iso(),
        correlation_id=str(event.correlation_id),
        task_id=event.detail.get("task_id") or None,
        decision=event.decision.value if event.decision is not None else None,
    )


@router.get("/logs", response_model=LogsResponse)
async def get_logs(
    request: Request,
    task_id: str | None = _TASK_QUERY,
    limit: int | None = _LIMIT_QUERY,
    since: str | None = _SINCE_QUERY,
) -> LogsResponse:
    services = _get_services(request)
    page = await run_in_threadpool(
        services.get_task_logs.query,
        task_id=task_id,
        limit=limit,
        since=since,
    )
    resolved_limit = limit if limit is not None else LOG_DEFAULT_LIMIT
    return LogsResponse(
        entries=[_log_entry_schema(e) for e in page.events],
        resolved_limit=resolved_limit,
        has_more=page.has_more,
        corrupt_count=page.corrupt_count,
        files_scanned=page.files_scanned,
    )
