"""v3 -> v4 migration and schema v4 integrity tests (CP1)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.core.domain.enums import MemoryType, TaskPriority, TaskSource, TaskStatus
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migration_v4 import SqliteDatabaseMigratorV4
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
    _check_json1_capability,
)
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from tests.conftest import FakeClock
from tests.support.legacy_schema_v1 import build_v1_database
from tests.support.legacy_schema_v3 import build_v3_database

_TS = "2026-06-20T00:00:00+00:00"
_TS_OBJ = UtcTimestamp(datetime(2026, 6, 20, tzinfo=UTC))

# ---------------------------------------------------------------------------
# 7.1 Fresh install
# ---------------------------------------------------------------------------


def test_fresh_bootstrap_creates_v4(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 4


def test_fresh_bootstrap_state_is_ready(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_fresh_schema_has_task_id_column(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    with Database(db_path).connect() as conn:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_records)")}
    assert "task_id" in cols


def test_fresh_schema_task_id_is_nullable(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    with Database(db_path).connect() as conn:
        row = next(
            r for r in conn.execute("PRAGMA table_info(memory_records)") if r[1] == "task_id"
        )
    # PRAGMA table_info: col[3] = notnull flag
    assert row[3] == 0  # nullable


def test_fresh_schema_idx_mem_task_exists(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    with Database(db_path).connect() as conn:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mem_task'"
        ).fetchone()
    assert row is not None


def test_fresh_bootstrap_json1_succeeds(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    # If JSON1 were unavailable, bootstrap would raise; reaching here means it passed.
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 4


# ---------------------------------------------------------------------------
# 7.2 v3 → v4 migration
# ---------------------------------------------------------------------------


def _seed_v3_with_task_and_memory(db_path: Path) -> None:
    build_v3_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO tasks VALUES ('T-LEGACY', 'legacy task', 'created', 'human', 'normal', ?, ?)",
            (_TS, _TS),
        )
        conn.execute(
            "INSERT INTO memory_records "
            "(id, type, title, summary, source, confidence, tags_json, created_at, deprecated) "
            "VALUES ('MEM-LEGACY', 'project_fact', 'legacy title', 'legacy summary', "
            "NULL, NULL, NULL, ?, 0)",
            (_TS,),
        )
        conn.commit()
    finally:
        conn.close()


def test_v3_to_v4_migration_version(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v3_with_task_and_memory(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 3

    SqliteDatabaseMigratorV4(clock).migrate(db_path)

    assert SqliteDatabaseInspector().schema_version(db_path) == 4


def test_v3_to_v4_preserves_existing_row(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v3_with_task_and_memory(db_path)
    SqliteDatabaseMigratorV4(clock).migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT id, title, summary, deprecated, task_id FROM memory_records WHERE id = 'MEM-LEGACY'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "MEM-LEGACY"
    assert row[1] == "legacy title"
    assert row[2] == "legacy summary"
    assert row[3] == 0
    assert row[4] is None  # legacy row: task_id = NULL


def test_v3_to_v4_index_created(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v3_with_task_and_memory(db_path)
    SqliteDatabaseMigratorV4(clock).migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_mem_task'"
        ).fetchone()
    finally:
        conn.close()
    assert row is not None


def test_v3_to_v4_reopen_succeeds(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v3_with_task_and_memory(db_path)
    SqliteDatabaseMigratorV4(clock).migrate(db_path)
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


# ---------------------------------------------------------------------------
# 7.3 Migration chain (top-level bootstrapper)
# ---------------------------------------------------------------------------


def test_chain_v1_to_v4(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v1_database(db_path)
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 4
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_chain_v2_to_v4(tmp_path: Path, clock: FakeClock) -> None:
    from ant_orchestrator.persistence.migration_v2 import SqliteDatabaseMigrator

    db_path = tmp_path / "state.sqlite"
    build_v1_database(db_path)
    SqliteDatabaseMigrator(clock).migrate(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 2

    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)

    assert SqliteDatabaseInspector().schema_version(db_path) == 4
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_chain_v3_to_v4(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v3_database(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 3

    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)

    assert SqliteDatabaseInspector().schema_version(db_path) == 4
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_chain_v1_data_preserved(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v1_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO tasks VALUES ('T-CHAIN', 'chain task', 'created', 'human', 'normal', ?, ?)",
            (_TS, _TS),
        )
        conn.commit()
    finally:
        conn.close()

    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)

    with Database(db_path).connect() as conn:
        row = conn.execute("SELECT title FROM tasks WHERE id = 'T-CHAIN'").fetchone()
    assert row is not None
    assert row[0] == "chain task"


# ---------------------------------------------------------------------------
# 7.4 Direct migrator fail-closed
# ---------------------------------------------------------------------------


def test_v4_migrator_rejects_v2_source(tmp_path: Path, clock: FakeClock) -> None:
    from ant_orchestrator.persistence.migration_v2 import SqliteDatabaseMigrator

    db_path = tmp_path / "state.sqlite"
    build_v1_database(db_path)
    SqliteDatabaseMigrator(clock).migrate(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 2

    with pytest.raises(SchemaVersionMismatch):
        SqliteDatabaseMigratorV4(clock).migrate(db_path)

    # DB remains at v2; no v4 row, no task_id column
    assert SqliteDatabaseInspector().schema_version(db_path) == 2
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(memory_records)")}
    finally:
        conn.close()
    assert "task_id" not in cols


def test_v4_migrator_rejects_v1_source(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v1_database(db_path)

    with pytest.raises(SchemaVersionMismatch):
        SqliteDatabaseMigratorV4(clock).migrate(db_path)

    assert SqliteDatabaseInspector().schema_version(db_path) == 1


def test_v4_failed_migration_rollback(tmp_path: Path, clock: FakeClock) -> None:
    """Simulate failure by pre-creating the index to trigger a duplicate-name error."""
    db_path = tmp_path / "state.sqlite"
    build_v3_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("ALTER TABLE memory_records ADD COLUMN task_id TEXT")
        conn.execute("CREATE INDEX idx_mem_task ON memory_records(task_id)")
        conn.commit()
    finally:
        conn.close()

    with pytest.raises(sqlite3.OperationalError):
        SqliteDatabaseMigratorV4(clock).migrate(db_path)

    # Rolled back: version still 3, no v4 migration row
    assert SqliteDatabaseInspector().schema_version(db_path) == 3


# ---------------------------------------------------------------------------
# 7.5 Idempotency
# ---------------------------------------------------------------------------


def test_bootstrap_v4_is_idempotent(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    boot = SqliteDatabaseBootstrapper(clock)
    boot.bootstrap(db_path)
    boot.bootstrap(db_path)  # second call: must be a no-op
    assert SqliteDatabaseInspector().schema_version(db_path) == 4


def test_v4_migrator_idempotent_on_v4(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v3_database(db_path)
    migrator = SqliteDatabaseMigratorV4(clock)
    migrator.migrate(db_path)
    migrator.migrate(db_path)  # second run: no-op, must not raise
    assert SqliteDatabaseInspector().schema_version(db_path) == 4


def test_idempotent_no_duplicate_migration_row(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    build_v3_database(db_path)
    migrator = SqliteDatabaseMigratorV4(clock)
    migrator.migrate(db_path)
    migrator.migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            "SELECT count(*) FROM schema_migrations WHERE version = 4"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 1


# ---------------------------------------------------------------------------
# 7.6 Repository round-trip
# ---------------------------------------------------------------------------


def _task_id_exists(db: Database) -> bool:
    from ant_orchestrator.core.domain.entities import Task

    try:
        SqliteTaskRepository(db).get(TaskId("TASK-RT"))
        return True
    except Exception:
        return False


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
    with pytest.raises(Exception):
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

    from ant_orchestrator.application.ports.database import RecordNotFound

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
