"""SQLite EnergyUsageRepository (PHASE_1_PLAN §7.3, Patch5)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.application.ports.database import StorageIntegrityError
from ant_orchestrator.core.domain.records import EnergyUsage
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.persistence.repositories.base import SqliteRepository

_COLUMNS = "id, task_id, worker_run_id, tokens_in, tokens_out, created_at"


def _to_energy_usage(row: sqlite3.Row) -> EnergyUsage:
    task_id = row["task_id"]
    worker_run_id = row["worker_run_id"]
    return EnergyUsage(
        id=EnergyUsageId(row["id"]),
        tokens_in=TokenCount(row["tokens_in"]),
        tokens_out=TokenCount(row["tokens_out"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        task_id=TaskId(task_id) if task_id is not None else None,
        worker_run_id=WorkerRunId(worker_run_id) if worker_run_id is not None else None,
    )


class SqliteEnergyUsageRepository(SqliteRepository):
    """Append-only persistence for energy usage records."""

    def append(self, usage: EnergyUsage) -> None:
        with self._db.transaction() as conn:
            self._check_ownership(conn, usage)
            conn.execute(
                f"INSERT INTO energy_usage ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    usage.id.value,
                    usage.task_id.value if usage.task_id is not None else None,
                    usage.worker_run_id.value if usage.worker_run_id is not None else None,
                    usage.tokens_in.value,
                    usage.tokens_out.value,
                    usage.created_at.to_iso(),
                ),
            )

    def get(self, usage_id: EnergyUsageId) -> EnergyUsage:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM energy_usage WHERE id = ?", (usage_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("EnergyUsage", usage_id.value)
        return _to_energy_usage(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[EnergyUsage]:
        return self._list("task_id", task_id.value)

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[EnergyUsage]:
        return self._list("worker_run_id", worker_run_id.value)

    def _list(self, column: str, value: str) -> Sequence[EnergyUsage]:
        with self._db.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM energy_usage WHERE {column} = ? ORDER BY created_at, id",
                (value,),
            ).fetchall()
        return [_to_energy_usage(row) for row in rows]

    @staticmethod
    def _check_ownership(conn: sqlite3.Connection, usage: EnergyUsage) -> None:
        if usage.task_id is None or usage.worker_run_id is None:
            return
        row = conn.execute(
            "SELECT task_id FROM worker_runs WHERE id = ?", (usage.worker_run_id.value,)
        ).fetchone()
        if row is None or row["task_id"] != usage.task_id.value:
            raise StorageIntegrityError("worker run does not belong to the given task")
