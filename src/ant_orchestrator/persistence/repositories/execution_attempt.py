"""Connection-bound ExecutionAttemptRepository (PHASE_4_PLAN C.9).

No exactly-once guarantee: the ``ux_attempt_active`` partial-unique index allows
only one PLANNED/STARTED attempt per logical action, while terminal attempts may
accumulate under distinct ``attempt_no`` values.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.value_objects import (
    ExecutionAttemptId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ExecutionAttempt
from ant_orchestrator.persistence.repositories.base import ConnRepository
from ant_orchestrator.persistence.serialization import iso_or_none, parse_iso_or_none

_COLUMNS = (
    "id, workflow_run_id, logical_action_id, attempt_no, status, owner_token, "
    "lease_expires_at, started_at, completed_at, outcome, created_at"
)
_ACTIVE = (ExecutionAttemptStatus.PLANNED.value, ExecutionAttemptStatus.STARTED.value)


def _to_attempt(row: sqlite3.Row) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=ExecutionAttemptId(row["id"]),
        workflow_run_id=WorkflowRunId(row["workflow_run_id"]),
        logical_action_id=row["logical_action_id"],
        attempt_no=int(row["attempt_no"]),
        status=ExecutionAttemptStatus.parse(row["status"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        owner_token=row["owner_token"],
        lease_expires_at=parse_iso_or_none(row["lease_expires_at"]),
        started_at=parse_iso_or_none(row["started_at"]),
        completed_at=parse_iso_or_none(row["completed_at"]),
        outcome=row["outcome"],
    )


def _values(attempt: ExecutionAttempt) -> tuple[object, ...]:
    return (
        attempt.id.value,
        attempt.workflow_run_id.value,
        attempt.logical_action_id,
        attempt.attempt_no,
        attempt.status.value,
        attempt.owner_token,
        iso_or_none(attempt.lease_expires_at),
        iso_or_none(attempt.started_at),
        iso_or_none(attempt.completed_at),
        attempt.outcome,
        attempt.created_at.to_iso(),
    )


class ExecutionAttemptRepository(ConnRepository):
    """Persists execution attempts within a unit of work."""

    def add(self, attempt: ExecutionAttempt) -> None:
        placeholders = ", ".join(["?"] * 11)
        self._conn.execute(
            f"INSERT INTO execution_attempts ({_COLUMNS}) VALUES ({placeholders})",
            _values(attempt),
        )

    def get(self, attempt_id: ExecutionAttemptId) -> ExecutionAttempt:
        row = self._conn.execute(
            "SELECT * FROM execution_attempts WHERE id = ?", (attempt_id.value,)
        ).fetchone()
        if row is None:
            raise self._missing("ExecutionAttempt", attempt_id.value)
        return _to_attempt(row)

    def update(self, attempt: ExecutionAttempt) -> None:
        cursor = self._conn.execute(
            "UPDATE execution_attempts SET status = ?, owner_token = ?, lease_expires_at = ?, "
            "started_at = ?, completed_at = ?, outcome = ? WHERE id = ?",
            (
                attempt.status.value,
                attempt.owner_token,
                iso_or_none(attempt.lease_expires_at),
                iso_or_none(attempt.started_at),
                iso_or_none(attempt.completed_at),
                attempt.outcome,
                attempt.id.value,
            ),
        )
        if cursor.rowcount == 0:
            raise self._missing("ExecutionAttempt", attempt.id.value)

    def find_active(self, run_id: WorkflowRunId, logical_action_id: str) -> ExecutionAttempt | None:
        row = self._conn.execute(
            "SELECT * FROM execution_attempts WHERE workflow_run_id = ? "
            "AND logical_action_id = ? AND status IN (?, ?)",
            (run_id.value, logical_action_id, *_ACTIVE),
        ).fetchone()
        return _to_attempt(row) if row is not None else None

    def find_settled_succeeded(
        self, run_id: WorkflowRunId, logical_action_id: str
    ) -> ExecutionAttempt | None:
        """Return the most recent SUCCEEDED attempt for the logical action, or None."""
        row = self._conn.execute(
            "SELECT * FROM execution_attempts WHERE workflow_run_id = ? "
            "AND logical_action_id = ? AND status = ? ORDER BY attempt_no DESC LIMIT 1",
            (run_id.value, logical_action_id, ExecutionAttemptStatus.SUCCEEDED.value),
        ).fetchone()
        return _to_attempt(row) if row is not None else None

    def list_for_action(
        self, run_id: WorkflowRunId, logical_action_id: str
    ) -> Sequence[ExecutionAttempt]:
        rows = self._conn.execute(
            "SELECT * FROM execution_attempts WHERE workflow_run_id = ? "
            "AND logical_action_id = ? ORDER BY attempt_no",
            (run_id.value, logical_action_id),
        ).fetchall()
        return [_to_attempt(row) for row in rows]
