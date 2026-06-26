"""v1 -> v2 migration: approvals table rebuild + Phase 4 tables (PHASE_4_PLAN CP1).

The ``approvals`` table is *rebuilt* (not altered) because v2 changes its CHECK
constraints (adds the ``cancelled`` status and the ``pending``/decided_at rule). The
migration runs in a single explicit transaction with foreign keys temporarily off
and a final ``foreign_key_check``; a failure mid-migration leaves the file at v1
(rolled back), never half-upgraded.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ant_orchestrator.application.ports.database import (
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.persistence.schema_common import CODE_MAX_VERSION, MIGRATIONS_TABLE
from ant_orchestrator.persistence.schema_workflow import (
    APPROVALS_V2_DDL,
    WORKFLOW_AUX_DDL,
    WORKFLOW_INDEX_DDL,
    WORKFLOW_RUNS_DDL,
)

_V1_VERSION = 1
# v1 columns carried over verbatim into the rebuilt v2 approvals table.
_APPROVAL_LEGACY_COLUMNS = "id, task_id, checkpoint_id, status, reason, requested_at, decided_at"
# idx_appr_task is dropped with the legacy approvals table and must be recreated.
_APPROVALS_TASK_INDEX = "CREATE INDEX idx_appr_task ON approvals(task_id)"


def _max_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


def _rebuild_approvals(conn: sqlite3.Connection) -> None:
    """Rebuild approvals into its v2 shape, preserving all existing rows."""
    conn.execute("ALTER TABLE approvals RENAME TO approvals_legacy_v1")
    conn.execute(APPROVALS_V2_DDL)
    conn.execute(
        f"INSERT INTO approvals ({_APPROVAL_LEGACY_COLUMNS}) "
        f"SELECT {_APPROVAL_LEGACY_COLUMNS} FROM approvals_legacy_v1"
    )
    conn.execute("DROP TABLE approvals_legacy_v1")


def _apply_v2(conn: sqlite3.Connection, applied_at: str) -> None:
    conn.execute(WORKFLOW_RUNS_DDL)
    _rebuild_approvals(conn)
    for ddl in WORKFLOW_AUX_DDL:
        conn.execute(ddl)
    conn.execute(_APPROVALS_TASK_INDEX)
    for ddl in WORKFLOW_INDEX_DDL:
        conn.execute(ddl)
    conn.execute(
        f"INSERT INTO {MIGRATIONS_TABLE} (version, applied_at) VALUES (?, ?)",
        (CODE_MAX_VERSION, applied_at),
    )


class SqliteDatabaseMigrator:
    """Upgrades a v1 database file to v2 (idempotent at v2; integrity-checked)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def migrate(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.isolation_level = None  # manual transaction control
        try:
            self._migrate_open(conn)
        finally:
            conn.execute("PRAGMA foreign_keys = ON")
            conn.close()

    def _migrate_open(self, conn: sqlite3.Connection) -> None:
        version = _max_version(conn)
        if version is None:
            raise StorageIntegrityError("schema_migrations is empty; cannot migrate")
        if version == CODE_MAX_VERSION:
            return  # already at v2: idempotent no-op
        if version != _V1_VERSION:
            raise SchemaVersionMismatch(f"cannot migrate from version {version} to v2")
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("BEGIN")
        try:
            _apply_v2(conn, self._clock.now().to_iso())
            violations = conn.execute("PRAGMA foreign_key_check").fetchall()
            if violations:
                raise StorageIntegrityError(f"migration left FK violations: {len(violations)}")
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
