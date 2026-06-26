"""Connection-bound StatusTransitionRepository (append-only; PHASE_4_PLAN C.13).

The ``ux_trans_operation`` UNIQUE index on ``(operation_id, subject)`` rejects a
duplicate transition when a unit of work is replayed with the same operation id.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.core.domain.enums import TransitionSubject, TransitionTrigger
from ant_orchestrator.core.domain.value_objects import (
    TransitionId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import StatusTransition
from ant_orchestrator.persistence.repositories.base import ConnRepository

_COLUMNS = (
    "id, workflow_run_id, subject, from_status, to_status, trigger, "
    "operation_id, causation_id, created_at"
)


def _to_transition(row: sqlite3.Row) -> StatusTransition:
    return StatusTransition(
        id=TransitionId(row["id"]),
        workflow_run_id=WorkflowRunId(row["workflow_run_id"]),
        subject=TransitionSubject.parse(row["subject"]),
        to_status=row["to_status"],
        trigger=TransitionTrigger.parse(row["trigger"]),
        operation_id=row["operation_id"],
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        from_status=row["from_status"],
        causation_id=row["causation_id"],
    )


class StatusTransitionRepository(ConnRepository):
    """Appends immutable lifecycle transitions within a unit of work."""

    def append(self, transition: StatusTransition) -> None:
        placeholders = ", ".join(["?"] * 9)
        self._conn.execute(
            f"INSERT INTO status_transitions ({_COLUMNS}) VALUES ({placeholders})",
            (
                transition.id.value,
                transition.workflow_run_id.value,
                transition.subject.value,
                transition.from_status,
                transition.to_status,
                transition.trigger.value,
                transition.operation_id,
                transition.causation_id,
                transition.created_at.to_iso(),
            ),
        )

    def list_by_run(self, run_id: WorkflowRunId) -> Sequence[StatusTransition]:
        rows = self._conn.execute(
            "SELECT * FROM status_transitions WHERE workflow_run_id = ? ORDER BY created_at, id",
            (run_id.value,),
        ).fetchall()
        return [_to_transition(row) for row in rows]
