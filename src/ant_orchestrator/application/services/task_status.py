"""GetTaskStatus — read-only status report across tasks (PHASE_4_PLAN CP7 §10).

Joins each task with its single active workflow run (if any) and that run's pending
approval gate, yielding a sanitized, framework-neutral view. No raw checkpoint state,
``request_json`` payload, or secret is ever exposed — only enum-derived status strings
and ids. The list is bounded to the most recent N tasks (no pagination framework yet).
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.services.workflow_support import UnitOfWorkFactory
from ant_orchestrator.config.constants import STATUS_RECENT_TASK_LIMIT
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.ports.unit_of_work import UnitOfWorkRepositories


@dataclass(frozen=True, slots=True)
class TaskStatusRow:
    """Sanitized status of one task and its active run/approval (if any)."""

    task_id: str
    title: str
    status: str
    priority: str
    workflow_run_id: str | None = None
    run_status: str | None = None
    pending_gate_type: str | None = None
    cancel_requested: bool = False


@dataclass(frozen=True, slots=True)
class TaskStatusReport:
    """A bounded, deterministically ordered set of task status rows."""

    rows: tuple[TaskStatusRow, ...]
    total: int
    truncated: bool


class GetTaskStatus:
    """Application read use case: report task/run/approval status deterministically."""

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def report(self, *, limit: int = STATUS_RECENT_TASK_LIMIT) -> TaskStatusReport:
        """Return the most-recent ``limit`` tasks in ``(created_at, id)`` order."""
        with self._uow_factory() as uow:
            tasks = list(uow.tasks.list())  # ordered by (created_at, id)
            total = len(tasks)
            recent = tasks[-limit:] if 0 < limit < total else tasks
            rows = tuple(self._row_for(uow, task) for task in recent)
        return TaskStatusReport(rows=rows, total=total, truncated=total > len(recent))

    @staticmethod
    def _row_for(uow: UnitOfWorkRepositories, task: Task) -> TaskStatusRow:
        """Build one row, joining the active run and its pending approval gate."""
        run = uow.workflow_runs.find_active_by_task(task.id)
        if run is None:
            return TaskStatusRow(
                task_id=task.id.value,
                title=task.title,
                status=task.status.value,
                priority=task.priority.value,
            )
        approval = uow.approvals.find_pending_by_run(run.id)
        gate_type = (
            approval.gate_type.value
            if approval is not None and approval.gate_type is not None
            else None
        )
        return TaskStatusRow(
            task_id=task.id.value,
            title=task.title,
            status=task.status.value,
            priority=task.priority.value,
            workflow_run_id=run.id.value,
            run_status=run.status.value,
            pending_gate_type=gate_type,
            cancel_requested=run.cancel_requested_at is not None,
        )
