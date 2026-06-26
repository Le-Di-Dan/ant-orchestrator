"""Connection-bound WorkflowRunRepository (PHASE_4_PLAN E.1).

Bound to a unit-of-work connection; the single-active-run-per-task invariant is
enforced by the ``ux_run_active_task`` partial-unique index, not by application code.
"""

from __future__ import annotations

import sqlite3

from ant_orchestrator.core.domain.enums import WorkflowRunStatus
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp, WorkflowRunId
from ant_orchestrator.core.domain.workflow import WorkflowRun
from ant_orchestrator.persistence.repositories.base import ConnRepository
from ant_orchestrator.persistence.serialization import iso_or_none, parse_iso_or_none

_COLUMNS = (
    "id, task_id, thread_id, status, workflow_definition_version, "
    "initial_invoke_operation_id, checkpoint_ever_observed, last_observed_checkpoint_id, "
    "cancel_requested_at, created_at, updated_at"
)


def _to_run(row: sqlite3.Row) -> WorkflowRun:
    return WorkflowRun(
        id=WorkflowRunId(row["id"]),
        task_id=TaskId(row["task_id"]),
        thread_id=row["thread_id"],
        status=WorkflowRunStatus.parse(row["status"]),
        workflow_definition_version=int(row["workflow_definition_version"]),
        initial_invoke_operation_id=row["initial_invoke_operation_id"],
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        updated_at=UtcTimestamp.from_iso(row["updated_at"]),
        checkpoint_ever_observed=bool(row["checkpoint_ever_observed"]),
        last_observed_checkpoint_id=row["last_observed_checkpoint_id"],
        cancel_requested_at=parse_iso_or_none(row["cancel_requested_at"]),
    )


def _values(run: WorkflowRun) -> tuple[object, ...]:
    return (
        run.id.value,
        run.task_id.value,
        run.thread_id,
        run.status.value,
        run.workflow_definition_version,
        run.initial_invoke_operation_id,
        int(run.checkpoint_ever_observed),
        run.last_observed_checkpoint_id,
        iso_or_none(run.cancel_requested_at),
        run.created_at.to_iso(),
        run.updated_at.to_iso(),
    )


class WorkflowRunRepository(ConnRepository):
    """Persists WorkflowRun execution identities within a unit of work."""

    def add(self, run: WorkflowRun) -> None:
        placeholders = ", ".join(["?"] * 11)
        self._conn.execute(
            f"INSERT INTO workflow_runs ({_COLUMNS}) VALUES ({placeholders})", _values(run)
        )

    def get(self, run_id: WorkflowRunId) -> WorkflowRun:
        row = self._conn.execute(
            "SELECT * FROM workflow_runs WHERE id = ?", (run_id.value,)
        ).fetchone()
        if row is None:
            raise self._missing("WorkflowRun", run_id.value)
        return _to_run(row)

    def find_active_by_task(self, task_id: TaskId) -> WorkflowRun | None:
        row = self._conn.execute(
            "SELECT * FROM workflow_runs WHERE task_id = ? AND status IN (?, ?)",
            (
                task_id.value,
                WorkflowRunStatus.RUNNING.value,
                WorkflowRunStatus.AWAITING_APPROVAL.value,
            ),
        ).fetchone()
        return _to_run(row) if row is not None else None

    def update(self, run: WorkflowRun) -> None:
        cursor = self._conn.execute(
            "UPDATE workflow_runs SET status = ?, checkpoint_ever_observed = ?, "
            "last_observed_checkpoint_id = ?, cancel_requested_at = ?, updated_at = ? "
            "WHERE id = ?",
            (
                run.status.value,
                int(run.checkpoint_ever_observed),
                run.last_observed_checkpoint_id,
                iso_or_none(run.cancel_requested_at),
                run.updated_at.to_iso(),
                run.id.value,
            ),
        )
        if cursor.rowcount == 0:
            raise self._missing("WorkflowRun", run.id.value)

    def compare_and_set_status(self, run: WorkflowRun, *, expected: WorkflowRunStatus) -> bool:
        """CAS guard: apply ``run`` only if the stored status still equals ``expected``."""
        cursor = self._conn.execute(
            "UPDATE workflow_runs SET status = ?, checkpoint_ever_observed = ?, "
            "last_observed_checkpoint_id = ?, cancel_requested_at = ?, updated_at = ? "
            "WHERE id = ? AND status = ?",
            (
                run.status.value,
                int(run.checkpoint_ever_observed),
                run.last_observed_checkpoint_id,
                iso_or_none(run.cancel_requested_at),
                run.updated_at.to_iso(),
                run.id.value,
                expected.value,
            ),
        )
        return cursor.rowcount > 0
