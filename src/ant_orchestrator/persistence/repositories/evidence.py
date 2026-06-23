"""SQLite ExecutionEvidenceRepository (PHASE_1_PLAN §7.3)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.records import ExecutionEvidence
from ant_orchestrator.core.domain.value_objects import EvidenceId, UtcTimestamp, WorkerRunId
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import dump_str_tuple, load_str_tuple

_COLUMNS = (
    "id, worker_run_id, files_read_json, files_changed_json, commands_json, result, created_at"
)


def _to_evidence(row: sqlite3.Row) -> ExecutionEvidence:
    return ExecutionEvidence(
        id=EvidenceId(row["id"]),
        worker_run_id=WorkerRunId(row["worker_run_id"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        files_read=load_str_tuple(row["files_read_json"]),
        files_changed=load_str_tuple(row["files_changed_json"]),
        commands=load_str_tuple(row["commands_json"]),
        result=row["result"],
    )


class SqliteExecutionEvidenceRepository(SqliteRepository):
    """Append-only persistence for execution evidence."""

    def append(self, evidence: ExecutionEvidence) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO execution_evidence ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    evidence.id.value,
                    evidence.worker_run_id.value,
                    dump_str_tuple(evidence.files_read),
                    dump_str_tuple(evidence.files_changed),
                    dump_str_tuple(evidence.commands),
                    evidence.result,
                    evidence.created_at.to_iso(),
                ),
            )

    def get(self, evidence_id: EvidenceId) -> ExecutionEvidence:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM execution_evidence WHERE id = ?", (evidence_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("ExecutionEvidence", evidence_id.value)
        return _to_evidence(row)

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[ExecutionEvidence]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM execution_evidence WHERE worker_run_id = ? ORDER BY created_at, id",
                (worker_run_id.value,),
            ).fetchall()
        return [_to_evidence(row) for row in rows]
