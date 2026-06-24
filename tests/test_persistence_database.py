"""Integration tests for SQLite bootstrap and inspection (CP4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
from ant_orchestrator.persistence.schema import MIGRATIONS_TABLE
from tests.conftest import FakeClock


def _bootstrapper(clock: FakeClock) -> SqliteDatabaseBootstrapper:
    return SqliteDatabaseBootstrapper(clock)


def test_inspect_missing(tmp_path: Path) -> None:
    inspector = SqliteDatabaseInspector()
    assert inspector.classify(tmp_path / "state.sqlite") is DatabaseState.MISSING


def test_bootstrap_fresh_then_ready(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    _bootstrapper(clock).bootstrap(db_path)
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_bootstrap_is_idempotent(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    boot = _bootstrapper(clock)
    boot.bootstrap(db_path)
    boot.bootstrap(db_path)  # must not raise
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.READY


def test_tables_without_migrations_is_corrupted(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE stray (id TEXT)")
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.CORRUPTED
    with pytest.raises(StorageIntegrityError):
        _bootstrapper(clock).bootstrap(db_path)


def test_incomplete_schema_is_corrupted(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(f"CREATE TABLE {MIGRATIONS_TABLE} (version INTEGER, applied_at TEXT)")
        conn.execute(f"INSERT INTO {MIGRATIONS_TABLE} VALUES (1, '2026-06-22T00:00:00+00:00')")
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.CORRUPTED
    with pytest.raises(StorageIntegrityError):
        _bootstrapper(clock).bootstrap(db_path)


def test_newer_version_is_incompatible(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    boot = _bootstrapper(clock)
    boot.bootstrap(db_path)
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute(f"INSERT INTO {MIGRATIONS_TABLE} VALUES (2, '2026-06-22T00:00:00+00:00')")
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.SCHEMA_INCOMPATIBLE
    with pytest.raises(SchemaVersionMismatch):
        boot.bootstrap(db_path)


def test_malformed_file_is_corrupted(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    db_path.write_bytes(b"this is not a sqlite database")
    assert SqliteDatabaseInspector().classify(db_path) is DatabaseState.CORRUPTED
