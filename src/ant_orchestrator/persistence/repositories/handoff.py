"""SQLite HandoffRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.records import HandoffRecord
from ant_orchestrator.core.domain.value_objects import HandoffId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository

_COLUMNS = "id, task_id, summary, what_changed, next_steps, created_at"


def _to_handoff(row: sqlite3.Row) -> HandoffRecord:
    return HandoffRecord(
        id=HandoffId(row["id"]),
        task_id=TaskId(row["task_id"]),
        summary=row["summary"],
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        what_changed=row["what_changed"],
        next_steps=row["next_steps"],
    )


class SqliteHandoffRepository(SqliteRepository):
    """Append-only persistence for handoff records."""

    def append(self, handoff: HandoffRecord) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO handoff_records ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    handoff.id.value,
                    handoff.task_id.value,
                    handoff.summary,
                    handoff.what_changed,
                    handoff.next_steps,
                    handoff.created_at.to_iso(),
                ),
            )

    def get(self, handoff_id: HandoffId) -> HandoffRecord:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM handoff_records WHERE id = ?", (handoff_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("HandoffRecord", handoff_id.value)
        return _to_handoff(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[HandoffRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM handoff_records WHERE task_id = ? ORDER BY created_at, id",
                (task_id.value,),
            ).fetchall()
        return [_to_handoff(row) for row in rows]
