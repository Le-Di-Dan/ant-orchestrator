"""v3 -> v4 migration and schema v4 integrity tests (CP1)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migration_v4 import SqliteDatabaseMigratorV4
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
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
            "INSERT INTO tasks VALUES"
            " ('T-LEGACY', 'legacy task', 'created', 'human', 'normal', ?, ?)",
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
            "SELECT id, title, summary, deprecated, task_id"
            " FROM memory_records WHERE id = 'MEM-LEGACY'"
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
            "INSERT INTO tasks VALUES"
            " ('T-CHAIN', 'chain task', 'created', 'human', 'normal', ?, ?)",
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
        count = conn.execute("SELECT count(*) FROM schema_migrations WHERE version = 4").fetchone()[
            0
        ]
    finally:
        conn.close()
    assert count == 1
