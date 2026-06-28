"""GetTaskLogs — validated audit log query returning bounded AuditLogPage (CP3)."""

from __future__ import annotations

from datetime import UTC, datetime

from ant_orchestrator.application.ports.audit_log_reader import (
    AuditLogPage,
    AuditLogQuery,
    AuditLogReader,
)
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT, LOG_MAX_LIMIT
from ant_orchestrator.core.domain.errors import DomainError


class GetTaskLogs:
    """Application use case: query audit logs with limit/since/task validation."""

    def __init__(self, reader: AuditLogReader) -> None:
        self._reader = reader

    def query(
        self,
        *,
        task_id: str | None = None,
        limit: int | None = None,
        since: str | None = None,
    ) -> AuditLogPage:
        resolved_limit = _resolve_log_limit(limit)
        since_dt = _parse_since(since)
        audit_query = AuditLogQuery(
            task_id=task_id or None,
            limit=resolved_limit,
            since=since_dt,
        )
        return self._reader.read(audit_query)


def _resolve_log_limit(raw: int | None) -> int:
    if raw is None:
        return LOG_DEFAULT_LIMIT
    if raw <= 0:
        raise DomainError(f"limit must be positive, got {raw}")
    if raw > LOG_MAX_LIMIT:
        raise DomainError(f"limit {raw} exceeds maximum {LOG_MAX_LIMIT}")
    return raw


def _parse_since(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DomainError(f"invalid since timestamp: {raw!r}") from exc
    if dt.tzinfo is None:
        raise DomainError(f"since timestamp must be timezone-aware, got {raw!r}")
    return dt.astimezone(UTC)
