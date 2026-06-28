"""SQLite MemoryRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import dump_str_tuple, load_str_tuple

_COLUMNS = (
    "id, type, title, summary, source, confidence, tags_json, created_at, deprecated, task_id"
)


def _to_memory(row: sqlite3.Row) -> MemoryRecord:
    confidence = row["confidence"]
    raw_task_id = row["task_id"]
    return MemoryRecord(
        id=MemoryId(row["id"]),
        type=MemoryType.parse(row["type"]),
        title=row["title"],
        summary=row["summary"],
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        source=row["source"],
        confidence=ConfidenceLevel.parse(confidence) if confidence is not None else None,
        tags=load_str_tuple(row["tags_json"]),
        deprecated=bool(row["deprecated"]),
        task_id=TaskId(raw_task_id) if raw_task_id is not None else None,
    )


class SqliteMemoryRepository(SqliteRepository):
    """Persistence for memory records (append/read/deprecate; no retrieval)."""

    def append(self, memory: MemoryRecord) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO memory_records ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    memory.id.value,
                    memory.type.value,
                    memory.title,
                    memory.summary,
                    memory.source,
                    memory.confidence.value if memory.confidence is not None else None,
                    dump_str_tuple(memory.tags),
                    memory.created_at.to_iso(),
                    int(memory.deprecated),
                    memory.task_id.value if memory.task_id is not None else None,
                ),
            )

    def get(self, memory_id: MemoryId) -> MemoryRecord:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM memory_records WHERE id = ?", (memory_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("MemoryRecord", memory_id.value)
        return _to_memory(row)

    def deprecate(self, memory: MemoryRecord) -> None:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE memory_records SET deprecated = 1 WHERE id = ?", (memory.id.value,)
            )
            if cursor.rowcount == 0:
                raise self._missing("MemoryRecord", memory.id.value)

    def list_by_type(self, memory_type: MemoryType) -> Sequence[MemoryRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM memory_records WHERE type = ? ORDER BY created_at, id",
                (memory_type.value,),
            ).fetchall()
        return [_to_memory(row) for row in rows]
