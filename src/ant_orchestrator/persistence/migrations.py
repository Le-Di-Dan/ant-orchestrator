"""Schema bootstrap and database-state classification (PHASE_1_PLAN §13.2, Patch7).

Bootstrap never trusts ``CREATE TABLE IF NOT EXISTS`` as proof of validity: it
inspects the actual tables/columns and distinguishes empty/partial/incompatible.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migration_v2 import SqliteDatabaseMigrator
from ant_orchestrator.persistence.migration_v3 import SqliteDatabaseMigratorV3
from ant_orchestrator.persistence.schema import (
    CODE_MAX_VERSION,
    EXPECTED_SCHEMA,
    INDEX_DDL,
    MIGRATIONS_TABLE,
    TABLE_DDL,
)


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(row[0]) for row in rows}


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _schema_is_complete(conn: sqlite3.Connection, tables: set[str]) -> bool:
    for table, columns in EXPECTED_SCHEMA.items():
        if table not in tables or not columns <= _column_names(conn, table):
            return False
    return True


def _max_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _classify_open(conn: sqlite3.Connection) -> DatabaseState:
    tables = _table_names(conn)
    if not tables or MIGRATIONS_TABLE not in tables:
        return DatabaseState.CORRUPTED
    version = _max_version(conn)
    if version is None:
        return DatabaseState.CORRUPTED
    if version > CODE_MAX_VERSION:
        return DatabaseState.SCHEMA_INCOMPATIBLE
    if not _schema_is_complete(conn, tables):
        return DatabaseState.CORRUPTED
    return DatabaseState.READY


class SqliteDatabaseInspector:
    """Classifies a database file without mutating it (implements DatabaseInspector)."""

    def classify(self, db_path: Path) -> DatabaseState:
        if not db_path.exists():
            return DatabaseState.MISSING
        try:
            with Database(db_path).connect() as conn:
                return _classify_open(conn)
        except sqlite3.DatabaseError:
            return DatabaseState.CORRUPTED

    def schema_version(self, db_path: Path) -> int | None:
        if not db_path.exists():
            return None
        try:
            with Database(db_path).connect() as conn:
                if MIGRATIONS_TABLE not in _table_names(conn):
                    return None
                return _max_version(conn)
        except sqlite3.DatabaseError:
            return None


class SqliteDatabaseBootstrapper:
    """Brings a database file to the current schema (implements DatabaseBootstrapper).

    Fresh files are created directly at the current version; an older (v1) file is
    upgraded in place via the v1->v2 migration; a file already at the current version
    is a verified no-op. The upgrade runs on its own connection after the inspection
    transaction closes (the migration toggles ``PRAGMA foreign_keys`` and manages its
    own transaction).
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._migrator_v2 = SqliteDatabaseMigrator(clock)
        self._migrator_v3 = SqliteDatabaseMigratorV3(clock)

    def bootstrap(self, db_path: Path) -> None:
        if self._inspect_for_bootstrap(db_path):
            self._migrator_v2.migrate(db_path)
            self._migrator_v3.migrate(db_path)

    def _inspect_for_bootstrap(self, db_path: Path) -> bool:
        """Create a fresh schema if empty; return True iff an upgrade is required."""
        with Database(db_path).transaction() as conn:
            tables = _table_names(conn)
            if not tables:
                self._create_schema(conn)
                return False
            if MIGRATIONS_TABLE not in tables:
                raise StorageIntegrityError("database has tables but no schema_migrations")
            version = _max_version(conn)
            if version is None:
                raise StorageIntegrityError("schema_migrations is empty")
            if version > CODE_MAX_VERSION:
                raise SchemaVersionMismatch(f"db version {version} > {CODE_MAX_VERSION}")
            if version < CODE_MAX_VERSION:
                return True  # upgrade after this transaction closes
            if not _schema_is_complete(conn, tables):
                raise StorageIntegrityError("database schema is incomplete")
            return False  # already current and complete: idempotent no-op

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        for ddl in TABLE_DDL:
            conn.execute(ddl)
        for ddl in INDEX_DDL:
            conn.execute(ddl)
        conn.execute(
            f"INSERT INTO {MIGRATIONS_TABLE} (version, applied_at) VALUES (?, ?)",
            (CODE_MAX_VERSION, self._clock.now().to_iso()),
        )
