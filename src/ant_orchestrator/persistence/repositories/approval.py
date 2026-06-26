"""ApprovalRepository — v2 schema, resolve-once + row-version CAS (PHASE_4_PLAN C.2/C.5).

``ApprovalRepository`` is connection-bound (used inside a unit of work);
``SqliteApprovalRepository`` is the standalone transaction-per-operation wrapper that
delegates to it, preserving the Phase 1 public API.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import ActorSource, ApprovalStatus, GateType
from ant_orchestrator.core.domain.errors import ApprovalAlreadyResolved
from ant_orchestrator.core.domain.records import Approval
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    CheckpointId,
    GateInstanceId,
    TaskId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.persistence.repositories.base import ConnRepository, SqliteRepository
from ant_orchestrator.persistence.serialization import (
    dump_payload,
    iso_or_none,
    load_payload,
    parse_iso_or_none,
)

_COLUMNS = (
    "id, task_id, checkpoint_id, status, reason, requested_at, decided_at, "
    "workflow_run_id, gate_type, gate_instance_id, approval_gate_sequence, actor_source, "
    "actor_label, approval_row_version, langgraph_checkpoint_id, langgraph_interrupt_id, "
    "request_json"
)


def _to_approval(row: sqlite3.Row) -> Approval:
    checkpoint_id = row["checkpoint_id"]
    run_id = row["workflow_run_id"]
    gate_instance = row["gate_instance_id"]
    request_json = row["request_json"]
    return Approval(
        id=ApprovalId(row["id"]),
        task_id=TaskId(row["task_id"]),
        status=ApprovalStatus.parse(row["status"]),
        requested_at=UtcTimestamp.from_iso(row["requested_at"]),
        checkpoint_id=CheckpointId(checkpoint_id) if checkpoint_id is not None else None,
        reason=row["reason"],
        decided_at=parse_iso_or_none(row["decided_at"]),
        workflow_run_id=WorkflowRunId(run_id) if run_id is not None else None,
        gate_type=GateType.parse(row["gate_type"]) if row["gate_type"] is not None else None,
        gate_instance_id=GateInstanceId(gate_instance) if gate_instance is not None else None,
        approval_gate_sequence=row["approval_gate_sequence"],
        actor_source=(
            ActorSource.parse(row["actor_source"]) if row["actor_source"] is not None else None
        ),
        actor_label=row["actor_label"],
        approval_row_version=int(row["approval_row_version"]),
        langgraph_checkpoint_id=row["langgraph_checkpoint_id"],
        langgraph_interrupt_id=row["langgraph_interrupt_id"],
        request_payload=load_payload(request_json) if request_json is not None else None,
    )


def _values(approval: Approval) -> tuple[object, ...]:
    return (
        approval.id.value,
        approval.task_id.value,
        approval.checkpoint_id.value if approval.checkpoint_id is not None else None,
        approval.status.value,
        approval.reason,
        approval.requested_at.to_iso(),
        iso_or_none(approval.decided_at),
        approval.workflow_run_id.value if approval.workflow_run_id is not None else None,
        approval.gate_type.value if approval.gate_type is not None else None,
        approval.gate_instance_id.value if approval.gate_instance_id is not None else None,
        approval.approval_gate_sequence,
        approval.actor_source.value if approval.actor_source is not None else None,
        approval.actor_label,
        approval.approval_row_version,
        approval.langgraph_checkpoint_id,
        approval.langgraph_interrupt_id,
        dump_payload(approval.request_payload) if approval.request_payload is not None else None,
    )


class ApprovalRepository(ConnRepository):
    """Connection-bound approvals repository (no own transaction; for a unit of work)."""

    def add(self, approval: Approval) -> None:
        placeholders = ", ".join(["?"] * 17)
        self._conn.execute(
            f"INSERT INTO approvals ({_COLUMNS}) VALUES ({placeholders})", _values(approval)
        )

    def resolve(self, approval: Approval) -> None:
        cursor = self._conn.execute(
            "UPDATE approvals SET status = ?, reason = ?, decided_at = ?, "
            "actor_source = ?, actor_label = ?, approval_row_version = ? "
            "WHERE id = ? AND status = ?",
            (
                approval.status.value,
                approval.reason,
                iso_or_none(approval.decided_at),
                approval.actor_source.value if approval.actor_source is not None else None,
                approval.actor_label,
                approval.approval_row_version,
                approval.id.value,
                ApprovalStatus.PENDING.value,
            ),
        )
        if cursor.rowcount == 0:
            self._raise_resolve_failure(approval.id)

    def resolve_with_version(self, approval: Approval, *, expected_version: int) -> bool:
        """CAS resolve: only succeeds if the stored row is pending at ``expected_version``."""
        cursor = self._conn.execute(
            "UPDATE approvals SET status = ?, reason = ?, decided_at = ?, "
            "actor_source = ?, actor_label = ?, approval_row_version = ? "
            "WHERE id = ? AND status = ? AND approval_row_version = ?",
            (
                approval.status.value,
                approval.reason,
                iso_or_none(approval.decided_at),
                approval.actor_source.value if approval.actor_source is not None else None,
                approval.actor_label,
                approval.approval_row_version,
                approval.id.value,
                ApprovalStatus.PENDING.value,
                expected_version,
            ),
        )
        return cursor.rowcount > 0

    def get(self, approval_id: ApprovalId) -> Approval:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE id = ?", (approval_id.value,)
        ).fetchone()
        if row is None:
            raise self._missing("Approval", approval_id.value)
        return _to_approval(row)

    def list_by_task(self, task_id: TaskId) -> Sequence[Approval]:
        rows = self._conn.execute(
            "SELECT * FROM approvals WHERE task_id = ? ORDER BY requested_at, id",
            (task_id.value,),
        ).fetchall()
        return [_to_approval(row) for row in rows]

    def find_by_gate_instance(self, gate_instance_id: GateInstanceId) -> Approval | None:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE gate_instance_id = ?", (gate_instance_id.value,)
        ).fetchone()
        return _to_approval(row) if row is not None else None

    def find_pending_by_run(self, workflow_run_id: WorkflowRunId) -> Approval | None:
        row = self._conn.execute(
            "SELECT * FROM approvals WHERE workflow_run_id = ? AND status = ?",
            (workflow_run_id.value, ApprovalStatus.PENDING.value),
        ).fetchone()
        return _to_approval(row) if row is not None else None

    def _raise_resolve_failure(self, approval_id: ApprovalId) -> None:
        exists = self._conn.execute(
            "SELECT 1 FROM approvals WHERE id = ?", (approval_id.value,)
        ).fetchone()
        if exists is None:
            raise self._missing("Approval", approval_id.value)
        raise ApprovalAlreadyResolved(f"Approval {approval_id.value} is not pending")


class SqliteApprovalRepository(SqliteRepository):
    """Standalone (transaction-per-operation) approvals repository (Phase 1 API)."""

    def add(self, approval: Approval) -> None:
        with self._db.transaction() as conn:
            ApprovalRepository(conn).add(approval)

    def resolve(self, approval: Approval) -> None:
        with self._db.transaction() as conn:
            ApprovalRepository(conn).resolve(approval)

    def resolve_with_version(self, approval: Approval, *, expected_version: int) -> bool:
        with self._db.transaction() as conn:
            return ApprovalRepository(conn).resolve_with_version(
                approval, expected_version=expected_version
            )

    def get(self, approval_id: ApprovalId) -> Approval:
        with self._db.connect() as conn:
            return ApprovalRepository(conn).get(approval_id)

    def list_by_task(self, task_id: TaskId) -> Sequence[Approval]:
        with self._db.connect() as conn:
            return ApprovalRepository(conn).list_by_task(task_id)

    def find_by_gate_instance(self, gate_instance_id: GateInstanceId) -> Approval | None:
        with self._db.connect() as conn:
            return ApprovalRepository(conn).find_by_gate_instance(gate_instance_id)

    def find_pending_by_run(self, workflow_run_id: WorkflowRunId) -> Approval | None:
        with self._db.connect() as conn:
            return ApprovalRepository(conn).find_pending_by_run(workflow_run_id)
