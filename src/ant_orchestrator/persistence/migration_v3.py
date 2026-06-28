"""v2 -> v3 migration: add ``resource_amounts_json`` to ``energy_usage`` (CP5).

CP5 records Test Ant wall-time and retry-delta in the existing ``energy_usage`` table
via a new nullable ``resource_amounts_json TEXT`` column.  ``ALTER TABLE ADD COLUMN``
is always backward-compatible in SQLite: existing rows get ``NULL`` (DocAnt semantics,
tokens only).  The migration runs in a single explicit transaction and records version 3
in ``schema_migrations`` on success; a failure rolls back and leaves the database at v2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ant_orchestrator.application.ports.database import (
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.persistence.schema_common import MIGRATIONS_TABLE

_V2_VERSION = 2
_V3_VERSION = 3


def _max_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


class SqliteDatabaseMigratorV3:
    """Upgrades a v2 database to v3 (idempotent at v3; integrity-checked)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def migrate(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.isolation_level = None  # manual transaction control
        try:
            self._migrate_open(conn)
        finally:
            conn.close()

    def _migrate_open(self, conn: sqlite3.Connection) -> None:
        version = _max_version(conn)
        if version is None:
            raise StorageIntegrityError("schema_migrations is empty; cannot migrate to v3")
        if version == _V3_VERSION:
            return  # already at v3: idempotent no-op
        if version != _V2_VERSION:
            raise SchemaVersionMismatch(f"cannot migrate to v3 from version {version}")
        conn.execute("BEGIN")
        try:
            conn.execute("ALTER TABLE energy_usage ADD COLUMN resource_amounts_json TEXT")
            conn.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (version, applied_at) VALUES (?, ?)",
                (_V3_VERSION, self._clock.now().to_iso()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
