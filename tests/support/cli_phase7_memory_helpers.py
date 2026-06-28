"""Shared helpers for Phase 7 CP6 memory CLI test suites."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.entities import Task
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
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME

cli = CliRunner()

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


def make_record(
    mem_id: str,
    *,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    title: str = "Test Title",
    summary: str = "summary content",
    source: str | None = "user",
    confidence: ConfidenceLevel | None = ConfidenceLevel.HIGH,
    tags: tuple[str, ...] = (),
    deprecated: bool = False,
    task_id: TaskId | None = None,
    offset: int = 0,
) -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=memory_type,
        title=title,
        summary=summary,
        created_at=ts(offset),
        source=source,
        confidence=confidence,
        tags=tags,
        deprecated=deprecated,
        task_id=task_id,
    )


def make_task(task_id: str, db: Database) -> TaskId:
    tid = TaskId(task_id)
    SqliteTaskRepository(db).add(
        Task(
            id=tid,
            title="task",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=ts(),
            updated_at=ts(),
        )
    )
    return tid


def db(root: Path) -> Database:
    return Database(root / ANT_DIRNAME / DATABASE_FILENAME)


def repo(root: Path) -> SqliteMemoryRepository:
    return SqliteMemoryRepository(db(root))


@pytest.fixture
def nest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = cli.invoke(app, ["init"])
    assert result.exit_code == 0, result.output
    return tmp_path
