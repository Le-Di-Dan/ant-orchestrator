"""AuditLogReader port — bounded, newest-first audit log query (Phase 7 CP3).

Port-owned types so application services never import from the adapters layer.
``AuditLogQuery.limit`` must be a positive resolved integer provided by the
calling service (the port does not import config constants).
``AuditLogQuery.since`` must be a UTC-aware datetime or None (no filter).
``AuditLogQuery.task_id`` is a raw string (or None) matching the ``task_id``
entry in the event's ``detail`` dict — the port does not know domain ID types.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from ant_orchestrator.application.ports.audit import AuditEvent


@dataclass(frozen=True, slots=True)
class AuditLogQuery:
    """Validated query parameters for bounded audit log retrieval."""

    task_id: str | None
    limit: int
    since: datetime | None


@dataclass(frozen=True, slots=True)
class AuditLogPage:
    """Result page from a bounded audit log read, newest matching events first."""

    events: tuple[AuditEvent, ...]
    corrupt_count: int
    files_scanned: int
    has_more: bool


class AuditLogReader(Protocol):
    """Read audit events in newest-first order with bounded memory."""

    def read(self, query: AuditLogQuery) -> AuditLogPage: ...
