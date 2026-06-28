"""v3 -> v4 migration: add nullable ``task_id`` to ``memory_records`` (CP1).

Phase 7 introduces task-scoped memory retrieval. ``memory_records.task_id`` is
nullable (existing records become ``NULL`` — workspace-scoped or legacy semantics).
The migration uses ``ALTER TABLE ADD COLUMN`` which is always backward-compatible
in SQLite: no existing row is modified. An index on ``task_id`` is added to support
efficient filtered retrieval in later checkpoints. The migration runs in a single
explicit transaction; a failure rolls back, leaving the database at v3.
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

_V3_VERSION = 3
_V4_VERSION = 4

_ALTER_ADD_TASK_ID = "ALTER TABLE memory_records ADD COLUMN task_id TEXT REFERENCES tasks(id)"
_CREATE_IDX_MEM_TASK = "CREATE INDEX idx_mem_task ON memory_records(task_id)"


def _max_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


class SqliteDatabaseMigratorV4:
    """Upgrades a v3 database to v4 (idempotent at v4; integrity-checked)."""

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
            raise StorageIntegrityError("schema_migrations is empty; cannot migrate to v4")
        if version == _V4_VERSION:
            return  # already at v4: idempotent no-op
        if version != _V3_VERSION:
            raise SchemaVersionMismatch(f"cannot migrate to v4 from version {version}")
        conn.execute("BEGIN")
        try:
            conn.execute(_ALTER_ADD_TASK_ID)
            conn.execute(_CREATE_IDX_MEM_TASK)
            conn.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (version, applied_at) VALUES (?, ?)",
                (_V4_VERSION, self._clock.now().to_iso()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
