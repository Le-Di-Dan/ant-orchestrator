"""SQLite TaskRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import TaskPriority, TaskSource, TaskStatus
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository

_COLUMNS = "id, title, status, source, priority, created_at, updated_at"


def _to_task(row: sqlite3.Row) -> Task:
    return Task(
        id=TaskId(row["id"]),
        title=row["title"],
        status=TaskStatus.parse(row["status"]),
        source=TaskSource.parse(row["source"]),
        priority=TaskPriority.parse(row["priority"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        updated_at=UtcTimestamp.from_iso(row["updated_at"]),
    )


def _values(task: Task) -> tuple[str, str, str, str, str, str, str]:
    return (
        task.id.value,
        task.title,
        task.status.value,
        task.source.value,
        task.priority.value,
        task.created_at.to_iso(),
        task.updated_at.to_iso(),
    )


class SqliteTaskRepository(SqliteRepository):
    """Persists Task entities."""

    def add(self, task: Task) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO tasks ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                _values(task),
            )

    def get(self, task_id: TaskId) -> Task:
        with self._db.connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id.value,)).fetchone()
        if row is None:
            raise self._missing("Task", task_id.value)
        return _to_task(row)

    def update(self, task: Task) -> None:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE tasks SET title = ?, status = ?, source = ?, priority = ?, "
                "created_at = ?, updated_at = ? WHERE id = ?",
                (
                    task.title,
                    task.status.value,
                    task.source.value,
                    task.priority.value,
                    task.created_at.to_iso(),
                    task.updated_at.to_iso(),
                    task.id.value,
                ),
            )
            if cursor.rowcount == 0:
                raise self._missing("Task", task.id.value)

    def list(self) -> Sequence[Task]:
        with self._db.connect() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at, id").fetchall()
        return [_to_task(row) for row in rows]
