"""API routes: POST /tasks, POST /tasks/{task_id}/workflow-runs, GET /tasks/{task_id}."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ant_orchestrator.api.schemas import (
    ApprovalSchema,
    CreateTaskRequest,
    EnergyTotalsSchema,
    TaskCreatedResponse,
    TaskDetailResponse,
    WorkerRunSummarySchema,
    WorkflowRunResponse,
    WorkflowRunSummarySchema,
)
from ant_orchestrator.application.models.execution_views import (
    ApprovalView,
    EnergyTotalsView,
    TaskDetailView,
    WorkerRunSummaryView,
    WorkflowRunSummaryView,
)
from ant_orchestrator.composition import WorkflowServices
from ant_orchestrator.core.domain.enums import TaskPriority

router = APIRouter()


def _get_services(request: Request) -> WorkflowServices:
    return request.app.state.services  # type: ignore[no-any-return]


def _energy_schema(view: EnergyTotalsView) -> EnergyTotalsSchema:
    return EnergyTotalsSchema(
        tokens_in=view.tokens_in,
        tokens_out=view.tokens_out,
        record_count=view.record_count,
    )


def _workflow_run_summary_schema(view: WorkflowRunSummaryView) -> WorkflowRunSummarySchema:
    return WorkflowRunSummarySchema(
        workflow_run_id=view.workflow_run_id,
        status=view.status,
        created_at=view.created_at,
        updated_at=view.updated_at,
        cancel_requested=view.cancel_requested,
    )


def _worker_run_summary_schema(view: WorkerRunSummaryView) -> WorkerRunSummarySchema:
    return WorkerRunSummarySchema(
        worker_run_id=view.worker_run_id,
        task_id=view.task_id,
        status=view.status,
        created_at=view.created_at,
        started_at=view.started_at,
        finished_at=view.finished_at,
    )


def _approval_schema(view: ApprovalView) -> ApprovalSchema:
    return ApprovalSchema(
        approval_id=view.approval_id,
        status=view.status,
        gate_type=view.gate_type,
        requested_at=view.requested_at,
        decided_at=view.decided_at,
        reason=view.reason,
    )


def _task_detail_response(view: TaskDetailView) -> TaskDetailResponse:
    return TaskDetailResponse(
        task_id=view.task_id,
        title=view.title,
        status=view.status,
        priority=view.priority,
        source=view.source,
        created_at=view.created_at,
        updated_at=view.updated_at,
        active_workflow_run=(
            _workflow_run_summary_schema(view.active_workflow_run)
            if view.active_workflow_run is not None
            else None
        ),
        worker_runs=[_worker_run_summary_schema(wr) for wr in view.worker_runs],
        energy_totals=_energy_schema(view.energy_totals),
        approvals=[_approval_schema(a) for a in view.approvals],
    )


@router.post("/tasks", status_code=201, response_model=TaskCreatedResponse)
async def create_task(body: CreateTaskRequest, request: Request) -> TaskCreatedResponse:
    services = _get_services(request)
    priority = TaskPriority.NORMAL
    if body.priority is not None:
        priority = TaskPriority.parse(body.priority)
    task = await run_in_threadpool(services.create_task.create, title=body.title, priority=priority)
    return TaskCreatedResponse(
        task_id=task.id.value,
        title=task.title,
        status=task.status.value,
        priority=task.priority.value,
        source=task.source.value,
        created_at=task.created_at.to_iso(),
    )


@router.post("/tasks/{task_id}/workflow-runs", response_model=WorkflowRunResponse)
async def run_workflow(task_id: str, request: Request) -> WorkflowRunResponse:
    services = _get_services(request)
    outcome = await run_in_threadpool(services.run_workflow.execute, task_id)
    return WorkflowRunResponse(
        workflow_run_id=outcome.run_id,
        status=outcome.status,
        approval_id=outcome.approval_id,
    )


@router.get("/tasks/{task_id}", response_model=TaskDetailResponse)
async def get_task(task_id: str, request: Request) -> TaskDetailResponse:
    services = _get_services(request)
    view = await run_in_threadpool(services.get_task_detail.get, task_id)
    return _task_detail_response(view)
