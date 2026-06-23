"""SQLite ApprovalRepository with resolve-once enforcement (PHASE_1_PLAN §7.3, D31)."""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import ApprovalStatus
from ant_orchestrator.core.domain.errors import ApprovalAlreadyResolved
from ant_orchestrator.core.domain.records import Approval
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    CheckpointId,
    TaskId,
    UtcTimestamp,
)
from ant_orchestrator.persistence.repositories.base import SqliteRepository
from ant_orchestrator.persistence.serialization import iso_or_none, parse_iso_or_none

_COLUMNS = "id, task_id, checkpoint_id, status, reason, requested_at, decided_at"


def _to_approval(row: sqlite3.Row) -> Approval:
    checkpoint_id = row["checkpoint_id"]
    return Approval(
        id=ApprovalId(row["id"]),
        task_id=TaskId(row["task_id"]),
        status=ApprovalStatus.parse(row["status"]),
        requested_at=UtcTimestamp.from_iso(row["requested_at"]),
        checkpoint_id=CheckpointId(checkpoint_id) if checkpoint_id is not None else None,
        reason=row["reason"],
        decided_at=parse_iso_or_none(row["decided_at"]),
    )


class SqliteApprovalRepository(SqliteRepository):
    """Persists approvals; ``resolve`` updates only a pending row."""

    def add(self, approval: Approval) -> None:
        with self._db.transaction() as conn:
            conn.execute(
                f"INSERT INTO approvals ({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    approval.id.value,
                    approval.task_id.value,
                    approval.checkpoint_id.value if approval.checkpoint_id is not None else None,
                    approval.status.value,
                    approval.reason,
                    approval.requested_at.to_iso(),
                    iso_or_none(approval.decided_at),
                ),
            )

    def resolve(self, approval: Approval) -> None:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "UPDATE approvals SET status = ?, reason = ?, decided_at = ? "
                "WHERE id = ? AND status = ?",
                (
                    approval.status.value,
                    approval.reason,
                    iso_or_none(approval.decided_at),
                    approval.id.value,
                    ApprovalStatus.PENDING.value,
                ),
            )
            if cursor.rowcount == 0:
                exists = conn.execute(
                    "SELECT 1 FROM approvals WHERE id = ?", (approval.id.value,)
                ).fetchone()
                if exists is None:
                    raise self._missing("Approval", approval.id.value)
                raise ApprovalAlreadyResolved(f"Approval {approval.id.value} is not pending")

    def get(self, approval_id: ApprovalId) -> Approval:
        with self._db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM approvals WHERE id = ?", (approval_id.value,)
            ).fetchone()
        if row is None:
            raise self._missing("Approval", approval_id.value)
        return _to_approval(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[Approval]:
        with self._db.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE task_id = ? ORDER BY requested_at, id",
                (task_id.value,),
            ).fetchall()
        return [_to_approval(row) for row in rows]
