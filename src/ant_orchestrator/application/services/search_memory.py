"""SearchMemory — bounded, filtered memory retrieval with audit evidence (CP3).

Validates raw request strings, resolves defaults, builds a typed
:class:`MemorySearchCriteria`, delegates to :class:`MemoryRepository`, and
emits a ``MEMORY_RETRIEVAL`` audit event. Never writes memory content, titles
or summaries into the audit detail — only aggregate metadata.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.config.constants import MEMORY_DEFAULT_LIMIT, MEMORY_MAX_LIMIT
from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.errors import DomainError
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.repositories import MemoryRepository


@dataclass(frozen=True, slots=True)
class MemorySearchRequest:
    """Raw presentation-layer input for memory search (strings, None = omitted)."""

    memory_type: str | None = None
    task_id: str | None = None
    source: str | None = None
    confidence: str | None = None
    tags: tuple[str, ...] = ()
    include_deprecated: bool = False
    limit: int | None = None


@dataclass(frozen=True, slots=True)
class MemorySearchResult:
    """Structured result of a memory search for downstream use."""

    records: tuple[MemoryRecord, ...]
    resolved_limit: int
    returned_count: int
    criteria: MemorySearchCriteria


class SearchMemory:
    """Application use case: search memory records with validation and audit."""

    def __init__(
        self,
        memory_repo: MemoryRepository,
        audit_sink: AuditSink,
        *,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._repo = memory_repo
        self._sink = audit_sink
        self._clock = clock
        self._ids = ids

    def execute(self, request: MemorySearchRequest) -> MemorySearchResult:
        resolved_limit = _resolve_limit(request.limit)
        for tag in request.tags:
            if not tag:
                raise DomainError("tag cannot be empty string")

        memory_type = _parse_memory_type(request.memory_type)
        confidence = _parse_confidence(request.confidence)
        task_id = TaskId(request.task_id) if request.task_id is not None else None

        criteria = MemorySearchCriteria(
            memory_type=memory_type,
            task_id=task_id,
            source=request.source,
            confidence=confidence,
            tags=request.tags,
            include_deprecated=request.include_deprecated,
            limit=resolved_limit,
        )

        records = self._repo.search(criteria)
        result = MemorySearchResult(
            records=tuple(records),
            resolved_limit=resolved_limit,
            returned_count=len(records),
            criteria=criteria,
        )

        self._emit_audit(request, criteria, result)
        return result

    def _emit_audit(
        self,
        request: MemorySearchRequest,
        criteria: MemorySearchCriteria,
        result: MemorySearchResult,
    ) -> None:
        detail: dict[str, str] = {
            "task_id": request.task_id or "",
            "memory_type": request.memory_type or "",
            "source": request.source or "",
            "confidence": request.confidence or "",
            "tags_count": str(len(criteria.tags)),
            "resolved_limit": str(criteria.limit),
            "returned_count": str(result.returned_count),
            "include_deprecated": str(criteria.include_deprecated).lower(),
        }
        event = AuditEvent(
            event_type=AuditEventType.MEMORY_RETRIEVAL,
            correlation_id=CorrelationId(self._ids.new_id()),
            created_at=self._clock.now(),
            detail=detail,
        )
        self._sink.write(event)


def _resolve_limit(raw: int | None) -> int:
    if raw is None:
        return MEMORY_DEFAULT_LIMIT
    if raw <= 0:
        raise DomainError(f"limit must be positive, got {raw}")
    if raw > MEMORY_MAX_LIMIT:
        raise DomainError(f"limit {raw} exceeds maximum {MEMORY_MAX_LIMIT}")
    return raw


def _parse_memory_type(raw: str | None) -> MemoryType | None:
    if raw is None:
        return None
    try:
        return MemoryType.parse(raw)
    except Exception as exc:
        raise DomainError(f"invalid memory_type: {raw!r}") from exc


def _parse_confidence(raw: str | None) -> ConfidenceLevel | None:
    if raw is None:
        return None
    try:
        return ConfidenceLevel.parse(raw)
    except Exception as exc:
        raise DomainError(f"invalid confidence: {raw!r}") from exc
