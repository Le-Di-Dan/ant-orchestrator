"""Shared helpers for Phase 7 memory retrieval test suites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    TaskPriority,
    TaskSource,
    TaskStatus,
)
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _ts(offset_seconds: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset_seconds))


def _mem(
    mem_id: str,
    *,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    title: str = "t",
    summary: str = "s",
    ts: UtcTimestamp | None = None,
    source: str | None = None,
    confidence: ConfidenceLevel | None = None,
    tags: tuple[str, ...] = (),
    deprecated: bool = False,
    task_id: TaskId | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=memory_type,
        title=title,
        summary=summary,
        created_at=ts or _ts(),
        source=source,
        confidence=confidence,
        tags=tags,
        deprecated=deprecated,
        task_id=task_id,
    )


def _seed_task(db: Database, task_id: str = "TASK-1") -> TaskId:
    from ant_orchestrator.core.domain.entities import Task

    SqliteTaskRepository(db).add(
        Task(
            id=TaskId(task_id),
            title="task",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=_ts(),
            updated_at=_ts(),
        )
    )
    return TaskId(task_id)
