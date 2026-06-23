"""SQLite CheckpointRepository (PHASE_1_PLAN §7.3, D33)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.records import WorkflowCheckpoint
from ant_orchestrator.core.domain.value_objects import CheckpointId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import dump_payload, load_payload

_COLUMNS = "id, task_id, payload_version, payload_json, created_at"


def _to_checkpoint(row: sqlite3.Row) -> WorkflowCheckpoint:
    return WorkflowCheckpoint(
        id=CheckpointId(row["id"]),
        task_id=TaskId(row["task_id"]),
        payload_version=row["payload_version"],
        payload=load_payload(row["payload_json"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
    )


class SqliteCheckpointRepository(SqliteRepository):
    """Append-only persistence for workflow checkpoints."""

    def append(self, checkpoint: WorkflowCheckpoint) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO workflow_checkpoints ({_COLUMNS}) VALUES (?, ?, ?, ?, ?)",
                (
                    checkpoint.id.value,
                    checkpoint.task_id.value,
                    checkpoint.payload_version,
                    dump_payload(checkpoint.payload),
                    checkpoint.created_at.to_iso(),
                ),
            )

    def get(self, checkpoint_id: CheckpointId) -> WorkflowCheckpoint:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_checkpoints WHERE id = ?", (checkpoint_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("WorkflowCheckpoint", checkpoint_id.value)
        return _to_checkpoint(row)

    def get_latest_by_task(self, task_id: TaskId) -> WorkflowCheckpoint:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM workflow_checkpoints WHERE task_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (task_id.value,),
            ).fetchone()
        if row is None:
            raise self._missing("WorkflowCheckpoint for task", task_id.value)
        return _to_checkpoint(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[WorkflowCheckpoint]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM workflow_checkpoints WHERE task_id = ? ORDER BY created_at, id",
                (task_id.value,),
            ).fetchall()
        return [_to_checkpoint(row) for row in rows]
