"""Schema v4 repository round-trip, cross-workspace isolation, and JSON1 tests (CP1)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import RecordNotFound, StorageIntegrityError
from ant_orchestrator.core.domain.enums import MemoryType, TaskPriority, TaskSource, TaskStatus
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    _check_json1_capability,
)
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from tests.conftest import FakeClock

_TS_OBJ = UtcTimestamp(datetime(2026, 6, 20, tzinfo=UTC))


def _seed_task(db: Database) -> None:
    from ant_orchestrator.core.domain.entities import Task

    SqliteTaskRepository(db).add(
        Task(
            id=TaskId("TASK-RT"),
            title="round-trip task",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=_TS_OBJ,
            updated_at=_TS_OBJ,
        )
    )


# ---------------------------------------------------------------------------
# 7.6 Repository round-trip
# ---------------------------------------------------------------------------


def test_memory_round_trip_task_id_none(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    record = MemoryRecord(
        id=MemoryId("MEM-A"),
        type=MemoryType.PROJECT_FACT,
        title="no task",
        summary="workspace-scoped",
        created_at=_TS_OBJ,
    )
    repo.append(record)
    fetched = repo.get(MemoryId("MEM-A"))
    assert fetched.task_id is None


def test_memory_round_trip_task_id_set(database: Database) -> None:
    _seed_task(database)
    repo = SqliteMemoryRepository(database)
    record = MemoryRecord(
        id=MemoryId("MEM-B"),
        type=MemoryType.PROJECT_FACT,
        title="with task",
        summary="task-scoped",
        created_at=_TS_OBJ,
        task_id=TaskId("TASK-RT"),
    )
    repo.append(record)
    fetched = repo.get(MemoryId("MEM-B"))
    assert fetched.task_id == TaskId("TASK-RT")


def test_memory_list_by_type_task_id_preserved(database: Database) -> None:
    _seed_task(database)
    repo = SqliteMemoryRepository(database)
    repo.append(
        MemoryRecord(
            id=MemoryId("MEM-C"),
            type=MemoryType.RISK_NOTE,
            title="risk",
            summary="risk record",
            created_at=_TS_OBJ,
            task_id=TaskId("TASK-RT"),
        )
    )
    results = repo.list_by_type(MemoryType.RISK_NOTE)
    assert len(results) == 1
    assert results[0].task_id == TaskId("TASK-RT")


def test_memory_foreign_key_nonexistent_task_rejected(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    record = MemoryRecord(
        id=MemoryId("MEM-D"),
        type=MemoryType.PROJECT_FACT,
        title="bad fk",
        summary="points to missing task",
        created_at=_TS_OBJ,
        task_id=TaskId("GHOST-TASK"),
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.append(record)


# ---------------------------------------------------------------------------
# 7.7 Cross-workspace isolation
# ---------------------------------------------------------------------------


def test_cross_workspace_isolation(tmp_path: Path, clock: FakeClock) -> None:
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_a)
    SqliteDatabaseBootstrapper(clock).bootstrap(db_b)

    repo_a = SqliteMemoryRepository(Database(db_a))
    repo_b = SqliteMemoryRepository(Database(db_b))

    repo_a.append(
        MemoryRecord(
            id=MemoryId("MEM-ISO"),
            type=MemoryType.PROJECT_FACT,
            title="a only",
            summary="only in workspace A",
            created_at=_TS_OBJ,
        )
    )

    with pytest.raises(RecordNotFound):
        repo_b.get(MemoryId("MEM-ISO"))

    assert len(repo_b.list_by_type(MemoryType.PROJECT_FACT)) == 0


# ---------------------------------------------------------------------------
# 7.8 JSON1 capability check
# ---------------------------------------------------------------------------


def test_json1_check_success_with_real_connection() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        _check_json1_capability(conn)  # must not raise
    finally:
        conn.close()


def test_json1_check_failure_raises_storage_integrity_error() -> None:
    class _FailingConn:
        def execute(self, sql: str, *args: object) -> None:
            raise sqlite3.OperationalError("no such function: json_each")

    with pytest.raises(StorageIntegrityError, match="JSON1"):
        _check_json1_capability(_FailingConn())  # type: ignore[arg-type]


def test_json1_check_failure_chains_original_exception() -> None:
    original = sqlite3.OperationalError("no such function: json_each")

    class _FailingConn:
        def execute(self, sql: str, *args: object) -> None:
            raise original

    with pytest.raises(StorageIntegrityError) as exc_info:
        _check_json1_capability(_FailingConn())  # type: ignore[arg-type]
    assert exc_info.value.__cause__ is original
