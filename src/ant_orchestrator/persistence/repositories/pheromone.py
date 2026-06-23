"""SQLite PheromoneRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import ConfidenceLevel, PheromoneType
from ant_orchestrator.core.domain.records import PheromoneRecord
from ant_orchestrator.core.domain.value_objects import PheromoneId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import (
    dump_str_tuple,
    iso_or_none,
    load_str_tuple,
    parse_iso_or_none,
)

_COLUMNS = "id, task_id, type, summary, files_json, expires_at, confidence, created_at"


def _to_pheromone(row: sqlite3.Row) -> PheromoneRecord:
    task_id = row["task_id"]
    confidence = row["confidence"]
    return PheromoneRecord(
        id=PheromoneId(row["id"]),
        type=PheromoneType.parse(row["type"]),
        summary=row["summary"],
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        task_id=TaskId(task_id) if task_id is not None else None,
        files=load_str_tuple(row["files_json"]),
        expires_at=parse_iso_or_none(row["expires_at"]),
        confidence=ConfidenceLevel.parse(confidence) if confidence is not None else None,
    )


class SqlitePheromoneRepository(SqliteRepository):
    """Append-only persistence for pheromone records."""

    def append(self, pheromone: PheromoneRecord) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO pheromones ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pheromone.id.value,
                    pheromone.task_id.value if pheromone.task_id is not None else None,
                    pheromone.type.value,
                    pheromone.summary,
                    dump_str_tuple(pheromone.files),
                    iso_or_none(pheromone.expires_at),
                    pheromone.confidence.value if pheromone.confidence is not None else None,
                    pheromone.created_at.to_iso(),
                ),
            )

    def get(self, pheromone_id: PheromoneId) -> PheromoneRecord:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM pheromones WHERE id = ?", (pheromone_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("PheromoneRecord", pheromone_id.value)
        return _to_pheromone(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[PheromoneRecord]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM pheromones WHERE task_id = ? ORDER BY created_at, id",
                (task_id.value,),
            ).fetchall()
        return [_to_pheromone(row) for row in rows]
