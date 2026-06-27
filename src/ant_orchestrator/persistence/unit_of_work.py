"""SQLite Unit of Work — one connection, one transaction (PHASE_4_PLAN C.13).

Groups several repository mutations into a single transaction: every repository it
hands out is bound to the same connection and never commits on its own. The unit of
work commits on clean exit and rolls back on any exception, so a partial failure can
never leave a half-written status-transition log.
"""

from __future__ import annotations

import sqlite3
from types import TracebackType

from ant_orchestrator.config.constants import SQLITE_BUSY_TIMEOUT_MS
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.approval import ApprovalRepository
from ant_orchestrator.persistence.repositories.execution_attempt import ExecutionAttemptRepository
from ant_orchestrator.persistence.repositories.execution_records import (
    ConnEnergyUsageRepository,
    ConnExecutionEvidenceRepository,
    ConnWorkerRunRepository,
)
from ant_orchestrator.persistence.repositories.resume_operation import ResumeOperationRepository
from ant_orchestrator.persistence.repositories.status_transition import StatusTransitionRepository
from ant_orchestrator.persistence.repositories.task import TaskRepository
from ant_orchestrator.persistence.repositories.workflow_run import WorkflowRunRepository


class UnitOfWorkRepositories:
    """Repositories bound to one open transaction (see ``core.ports.unit_of_work``)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.tasks = TaskRepository(conn)
        self.approvals = ApprovalRepository(conn)
        self.workflow_runs = WorkflowRunRepository(conn)
        self.transitions = StatusTransitionRepository(conn)
        self.execution_attempts = ExecutionAttemptRepository(conn)
        self.resume_operations = ResumeOperationRepository(conn)
        # Phase 5 CP6: execution records persisted atomically with the rest of the UoW.
        self.worker_runs = ConnWorkerRunRepository(conn)
        self.evidence = ConnExecutionEvidenceRepository(conn)
        self.energy_usage = ConnEnergyUsageRepository(conn)


class SqliteUnitOfWork:
    """A context manager that commits on clean exit and rolls back on any error."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._conn: sqlite3.Connection | None = None

    def __enter__(self) -> UnitOfWorkRepositories:
        conn = sqlite3.connect(str(self._db.path))
        conn.row_factory = sqlite3.Row
        conn.isolation_level = None  # explicit BEGIN/COMMIT below
        conn.execute("PRAGMA foreign_keys = ON")
        # Wait (rather than fail) for a contended lock, and take the write lock at
        # transaction start so two concurrent writers serialize instead of dead-locking
        # on a deferred read-then-upgrade (PHASE_4_PLAN CP8 — concurrent approve race).
        conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
        conn.execute("BEGIN IMMEDIATE")
        self._conn = conn
        return UnitOfWorkRepositories(conn)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        conn = self._conn
        if conn is None:  # pragma: no cover - defensive
            return
        try:
            if exc_type is None:
                conn.execute("COMMIT")
            else:
                conn.execute("ROLLBACK")
        finally:
            conn.close()
            self._conn = None
