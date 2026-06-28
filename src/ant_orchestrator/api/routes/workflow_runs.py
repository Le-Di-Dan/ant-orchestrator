"""API route: GET /workflow-runs/{workflow_run_id}."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ant_orchestrator.api.schemas import WorkflowRunDetailResponse
from ant_orchestrator.composition import WorkflowServices

router = APIRouter()


def _get_services(request: Request) -> WorkflowServices:
    return request.app.state.services  # type: ignore[no-any-return]


@router.get("/workflow-runs/{workflow_run_id}", response_model=WorkflowRunDetailResponse)
async def get_workflow_run(workflow_run_id: str, request: Request) -> WorkflowRunDetailResponse:
    services = _get_services(request)
    view = await run_in_threadpool(services.get_workflow_run_detail.get, workflow_run_id)
    return WorkflowRunDetailResponse(
        workflow_run_id=view.workflow_run_id,
        task_id=view.task_id,
        status=view.status,
        workflow_definition_version=view.workflow_definition_version,
        created_at=view.created_at,
        updated_at=view.updated_at,
        cancel_requested=view.cancel_requested,
    )
