"""SQLite WorkerRunRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.entities import WorkerRun
from ant_orchestrator.core.domain.enums import WorkerRunStatus
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp, WorkerRunId
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import iso_or_none, parse_iso_or_none

_COLUMNS = "id, task_id, status, started_at, finished_at, created_at"


def _to_worker_run(row: sqlite3.Row) -> WorkerRun:
    return WorkerRun(
        id=WorkerRunId(row["id"]),
        task_id=TaskId(row["task_id"]),
        status=WorkerRunStatus.parse(row["status"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        started_at=parse_iso_or_none(row["started_at"]),
        finished_at=parse_iso_or_none(row["finished_at"]),
    )


def _values(run: WorkerRun) -> tuple[str, str, str, str | None, str | None, str]:
    return (
        run.id.value,
        run.task_id.value,
        run.status.value,
        iso_or_none(run.started_at),
        iso_or_none(run.finished_at),
        run.created_at.to_iso(),
    )


class SqliteWorkerRunRepository(SqliteRepository):
    """Persists WorkerRun entities."""

    def add(self, worker_run: WorkerRun) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO worker_runs ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                _values(worker_run),
            )

    def get(self, worker_run_id: WorkerRunId) -> WorkerRun:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM worker_runs WHERE id = ?", (worker_run_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("WorkerRun", worker_run_id.value)
        return _to_worker_run(row)

    def update(self, worker_run: WorkerRun) -> None:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE worker_runs SET task_id = ?, status = ?, started_at = ?, "
                "finished_at = ?, created_at = ? WHERE id = ?",
                (
                    worker_run.task_id.value,
                    worker_run.status.value,
                    iso_or_none(worker_run.started_at),
                    iso_or_none(worker_run.finished_at),
                    worker_run.created_at.to_iso(),
                    worker_run.id.value,
                ),
            )
            if cursor.rowcount == 0:
                raise self._missing("WorkerRun", worker_run.id.value)

    def list_by_task(self, task_id: TaskId) -> Sequence[WorkerRun]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM worker_runs WHERE task_id = ? ORDER BY created_at, id",
                (task_id.value,),
            ).fetchall()
        return [_to_worker_run(row) for row in rows]
