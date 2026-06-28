"""GetTaskDetail — full observable task read model for CLI/API (CP3)."""

from __future__ import annotations

from ant_orchestrator.application.models.execution_views import (
    ApprovalView,
    EnergyTotalsView,
    TaskDetailView,
    WorkerRunSummaryView,
    WorkflowRunSummaryView,
)
from ant_orchestrator.config.constants import (
    TASK_DETAIL_APPROVAL_LIMIT,
    TASK_DETAIL_WORKER_RUN_LIMIT,
)
from ant_orchestrator.core.domain.entities import WorkerRun
from ant_orchestrator.core.domain.records import Approval, EnergyUsage
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.core.domain.workflow import WorkflowRun
from ant_orchestrator.core.ports.repositories import (
    ApprovalRepository,
    EnergyUsageRepository,
    TaskRepository,
    WorkerRunRepository,
    WorkflowRunRepository,
)


class GetTaskDetail:
    """Application use case: build full task detail view from standalone repositories."""

    def __init__(
        self,
        task_repo: TaskRepository,
        workflow_run_repo: WorkflowRunRepository,
        worker_run_repo: WorkerRunRepository,
        energy_repo: EnergyUsageRepository,
        approval_repo: ApprovalRepository,
    ) -> None:
        self._tasks = task_repo
        self._workflow_runs = workflow_run_repo
        self._worker_runs = worker_run_repo
        self._energy = energy_repo
        self._approvals = approval_repo

    def get(self, task_id_value: str) -> TaskDetailView:
        task_id = TaskId(task_id_value)
        task = self._tasks.get(task_id)

        active_run = self._workflow_runs.find_active_by_task(task_id)
        run_summary = _workflow_run_summary(active_run) if active_run is not None else None

        worker_runs_raw = list(self._worker_runs.list_by_task(task_id))
        worker_runs_raw.sort(key=lambda r: r.created_at.value, reverse=True)
        worker_runs_bounded = worker_runs_raw[:TASK_DETAIL_WORKER_RUN_LIMIT]

        energy_list = list(self._energy.list_by_task(task_id))
        energy_totals = _aggregate_energy(energy_list)

        approvals_raw = list(self._approval_repo.list_by_task(task_id))
        approvals_raw.sort(key=lambda a: a.requested_at.value, reverse=True)
        approvals_bounded = approvals_raw[:TASK_DETAIL_APPROVAL_LIMIT]

        return TaskDetailView(
            task_id=task.id.value,
            title=task.title,
            status=task.status.value,
            priority=task.priority.value,
            source=task.source.value,
            created_at=task.created_at.to_iso(),
            updated_at=task.updated_at.to_iso(),
            active_workflow_run=run_summary,
            worker_runs=tuple(_worker_run_summary(wr) for wr in worker_runs_bounded),
            energy_totals=energy_totals,
            approvals=tuple(_approval_view(a) for a in approvals_bounded),
        )

    @property
    def _approval_repo(self) -> ApprovalRepository:
        return self._approvals


def _workflow_run_summary(run: WorkflowRun) -> WorkflowRunSummaryView:
    return WorkflowRunSummaryView(
        workflow_run_id=run.id.value,
        status=run.status.value,
        created_at=run.created_at.to_iso(),
        updated_at=run.updated_at.to_iso(),
        cancel_requested=run.cancel_requested_at is not None,
    )


def _worker_run_summary(run: WorkerRun) -> WorkerRunSummaryView:
    started = run.started_at.to_iso() if run.started_at is not None else None
    finished = run.finished_at.to_iso() if run.finished_at is not None else None
    return WorkerRunSummaryView(
        worker_run_id=run.id.value,
        task_id=run.task_id.value,
        status=run.status.value,
        created_at=run.created_at.to_iso(),
        started_at=started,
        finished_at=finished,
    )


def _aggregate_energy(records: list[EnergyUsage]) -> EnergyTotalsView:
    return EnergyTotalsView(
        tokens_in=sum(r.tokens_in.value for r in records),
        tokens_out=sum(r.tokens_out.value for r in records),
        record_count=len(records),
    )


def _approval_view(a: Approval) -> ApprovalView:
    gate_type = a.gate_type.value if a.gate_type is not None else None
    decided = a.decided_at.to_iso() if a.decided_at is not None else None
    return ApprovalView(
        approval_id=a.id.value,
        status=a.status.value,
        gate_type=gate_type,
        requested_at=a.requested_at.to_iso(),
        decided_at=decided,
        reason=a.reason,
    )
