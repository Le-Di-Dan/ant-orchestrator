"""v4 -> v5 migration: add task_results and task_result_artifacts tables (CP4).

Phase 8 CP4 introduces durable task-result persistence. Two new tables are
added: ``task_results`` (one-per-WorkflowRun terminal result) and
``task_result_artifacts`` (artifact refs linked to a result). Both carry FK
constraints. The migration runs in a single explicit transaction; failure rolls
back, leaving the database at v4.
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

_V4_VERSION = 4
_V5_VERSION = 5

_CREATE_TASK_RESULTS = """\
CREATE TABLE task_results (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    workflow_run_id TEXT NOT NULL UNIQUE REFERENCES workflow_runs(id) ON DELETE RESTRICT,
    outcome TEXT NOT NULL CHECK (outcome IN ('completed', 'failed', 'rejected', 'cancelled')),
    summary TEXT NOT NULL,
    failure_code TEXT,
    failure_message TEXT,
    failure_retryable INTEGER CHECK (failure_retryable IN (0, 1)),
    failure_source TEXT,
    finalized_at TEXT NOT NULL,
    result_version INTEGER NOT NULL
)"""

_CREATE_TASK_RESULT_ARTIFACTS = """\
CREATE TABLE task_result_artifacts (
    id TEXT PRIMARY KEY NOT NULL,
    task_result_id TEXT NOT NULL REFERENCES task_results(id) ON DELETE RESTRICT,
    kind TEXT NOT NULL CHECK (kind IN ('internal', 'staged', 'applied')),
    relative_path TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    created_by_attempt_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('pending', 'final', 'rejected')),
    metadata_json TEXT,
    created_at TEXT NOT NULL
)"""

_CREATE_IDX_RESULTS_TASK = "CREATE INDEX idx_task_results_task ON task_results(task_id)"
_CREATE_IDX_RESULTS_RUN = "CREATE INDEX idx_task_results_run ON task_results(workflow_run_id)"
_CREATE_IDX_ARTIFACTS_RESULT = (
    "CREATE INDEX idx_trarr_result ON task_result_artifacts(task_result_id)"
)


def _max_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute(f"SELECT MAX(version) FROM {MIGRATIONS_TABLE}").fetchone()
    if row is None or row[0] is None:
        return None
    return int(row[0])


class SqliteDatabaseMigratorV5:
    """Upgrades a v4 database to v5 (idempotent at v5; integrity-checked)."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def migrate(self, db_path: Path) -> None:
        conn = sqlite3.connect(str(db_path))
        conn.isolation_level = None
        try:
            self._migrate_open(conn)
        finally:
            conn.close()

    def _migrate_open(self, conn: sqlite3.Connection) -> None:
        version = _max_version(conn)
        if version is None:
            raise StorageIntegrityError("schema_migrations is empty; cannot migrate to v5")
        if version == _V5_VERSION:
            return
        if version != _V4_VERSION:
            raise SchemaVersionMismatch(f"cannot migrate to v5 from version {version}")
        conn.execute("BEGIN")
        try:
            conn.execute(_CREATE_TASK_RESULTS)
            conn.execute(_CREATE_TASK_RESULT_ARTIFACTS)
            conn.execute(_CREATE_IDX_RESULTS_TASK)
            conn.execute(_CREATE_IDX_RESULTS_RUN)
            conn.execute(_CREATE_IDX_ARTIFACTS_RESULT)
            conn.execute(
                f"INSERT INTO {MIGRATIONS_TABLE} (version, applied_at) VALUES (?, ?)",
                (_V5_VERSION, self._clock.now().to_iso()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
