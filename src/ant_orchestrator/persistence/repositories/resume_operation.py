"""Connection-bound ResumeOperationRepository (PHASE_4_PLAN C.5b).

``ux_resume_approval`` (UNIQUE on approval_id) guarantees one logical resume
operation per approval; ``ux_resume_interrupt`` is defense-in-depth on the
(run, interrupt) pair.
"""

from __future__ import annotations

import sqlite3

from ant_orchestrator.core.domain.enums import ApprovalStatus, ResumeOperationStatus
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    ResumeOperationId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ResumeOperation
from ant_orchestrator.persistence.repositories.base import ConnRepository
from ant_orchestrator.persistence.serialization import iso_or_none, parse_iso_or_none

_COLUMNS = (
    "id, workflow_run_id, approval_id, decision, status, langgraph_checkpoint_id, "
    "langgraph_interrupt_id, owner_token, lease_expires_at, completed_at, created_at"
)


def _to_operation(row: sqlite3.Row) -> ResumeOperation:
    return ResumeOperation(
        id=ResumeOperationId(row["id"]),
        workflow_run_id=WorkflowRunId(row["workflow_run_id"]),
        approval_id=ApprovalId(row["approval_id"]),
        decision=ApprovalStatus.parse(row["decision"]),
        status=ResumeOperationStatus.parse(row["status"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        langgraph_checkpoint_id=row["langgraph_checkpoint_id"],
        langgraph_interrupt_id=row["langgraph_interrupt_id"],
        owner_token=row["owner_token"],
        lease_expires_at=parse_iso_or_none(row["lease_expires_at"]),
        completed_at=parse_iso_or_none(row["completed_at"]),
    )


def _values(operation: ResumeOperation) -> tuple[object, ...]:
    return (
        operation.id.value,
        operation.workflow_run_id.value,
        operation.approval_id.value,
        operation.decision.value,
        operation.status.value,
        operation.langgraph_checkpoint_id,
        operation.langgraph_interrupt_id,
        operation.owner_token,
        iso_or_none(operation.lease_expires_at),
        iso_or_none(operation.completed_at),
        operation.created_at.to_iso(),
    )


class ResumeOperationRepository(ConnRepository):
    """Persists resume-operation owner leases within a unit of work."""

    def add(self, operation: ResumeOperation) -> None:
        placeholders = ", ".join(["?"] * 11)
        self._conn.execute(
            f"INSERT INTO resume_operations ({_COLUMNS}) VALUES ({placeholders})",
            _values(operation),
        )

    def get(self, operation_id: ResumeOperationId) -> ResumeOperation:
        row = self._conn.execute(
            "SELECT * FROM resume_operations WHERE id = ?", (operation_id.value,)
        ).fetchone()
        if row is None:
            raise self._missing("ResumeOperation", operation_id.value)
        return _to_operation(row)

    def update(self, operation: ResumeOperation) -> None:
        cursor = self._conn.execute(
            "UPDATE resume_operations SET decision = ?, status = ?, "
            "langgraph_checkpoint_id = ?, langgraph_interrupt_id = ?, owner_token = ?, "
            "lease_expires_at = ?, completed_at = ? WHERE id = ?",
            (
                operation.decision.value,
                operation.status.value,
                operation.langgraph_checkpoint_id,
                operation.langgraph_interrupt_id,
                operation.owner_token,
                iso_or_none(operation.lease_expires_at),
                iso_or_none(operation.completed_at),
                operation.id.value,
            ),
        )
        if cursor.rowcount == 0:
            raise self._missing("ResumeOperation", operation.id.value)

    def find_by_approval(self, approval_id: ApprovalId) -> ResumeOperation | None:
        row = self._conn.execute(
            "SELECT * FROM resume_operations WHERE approval_id = ?", (approval_id.value,)
        ).fetchone()
        return _to_operation(row) if row is not None else None
