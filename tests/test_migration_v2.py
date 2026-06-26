"""v1 -> v2 migration integrity tests (CP1)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
)
from ant_orchestrator.persistence.migration_v2 import SqliteDatabaseMigrator
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
from tests.conftest import FakeClock
from tests.support.legacy_schema_v1 import build_v1_database

_REQ_AT = "2026-06-20T00:00:00+00:00"


def _seed_v1(db_path: Path) -> None:
    build_v1_database(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "INSERT INTO tasks VALUES ('T1', 'demo', 'created', 'human', 'normal', ?, ?)",
            (_REQ_AT, _REQ_AT),
        )
        conn.execute(
            "INSERT INTO approvals (id, task_id, status, reason, requested_at) "
            "VALUES ('A1', 'T1', 'pending', NULL, ?)",
            (_REQ_AT,),
        )
        conn.commit()
    finally:
        conn.close()


def test_migrate_v1_to_v2_is_ready(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 1

    SqliteDatabaseMigrator(clock).migrate(db_path)

    inspector = SqliteDatabaseInspector()
    assert inspector.classify(db_path) is DatabaseState.READY
    assert inspector.schema_version(db_path) == 2


def test_migration_preserves_existing_rows(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    SqliteDatabaseMigrator(clock).migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT task_id, status, approval_row_version, workflow_run_id FROM approvals "
            "WHERE id = 'A1'"
        ).fetchone()
    finally:
        conn.close()
    assert row == ("T1", "pending", 1, None)


def test_migration_leaves_no_fk_violations(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    SqliteDatabaseMigrator(clock).migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        conn.close()
    assert violations == []


def test_migration_is_idempotent(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    migrator = SqliteDatabaseMigrator(clock)
    migrator.migrate(db_path)
    migrator.migrate(db_path)  # second run: no-op, must not raise
    assert SqliteDatabaseInspector().schema_version(db_path) == 2


def test_migration_on_fresh_v2_is_noop(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)  # fresh v2
    SqliteDatabaseMigrator(clock).migrate(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 2


def test_migration_rejects_unsupported_version(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (3, ?)", (_REQ_AT,)
        )
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(SchemaVersionMismatch):
        SqliteDatabaseMigrator(clock).migrate(db_path)


def test_migration_v2_adds_cancelled_status_support(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _seed_v1(db_path)
    SqliteDatabaseMigrator(clock).migrate(db_path)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        # The v1 CHECK forbade 'cancelled'; the rebuilt v2 table must accept it.
        conn.execute(
            "INSERT INTO approvals (id, task_id, status, requested_at, decided_at) "
            "VALUES ('A2', 'T1', 'cancelled', ?, ?)",
            (_REQ_AT, _REQ_AT),
        )
        conn.commit()
        status = conn.execute("SELECT status FROM approvals WHERE id = 'A2'").fetchone()[0]
    finally:
        conn.close()
    assert status == "cancelled"
