"""API route: GET /worker-runs/{worker_run_id}."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool

from ant_orchestrator.api.schemas import (
    EnergyTotalsSchema,
    EvidenceSummarySchema,
    WorkerRunDetailResponse,
)
from ant_orchestrator.application.models.execution_views import (
    EnergyTotalsView,
    EvidenceSummaryView,
)
from ant_orchestrator.composition import WorkflowServices

router = APIRouter()


def _get_services(request: Request) -> WorkflowServices:
    return request.app.state.services  # type: ignore[no-any-return]


def _energy_schema(view: EnergyTotalsView) -> EnergyTotalsSchema:
    return EnergyTotalsSchema(
        tokens_in=view.tokens_in,
        tokens_out=view.tokens_out,
        record_count=view.record_count,
    )


def _evidence_schema(view: EvidenceSummaryView) -> EvidenceSummarySchema:
    return EvidenceSummarySchema(
        evidence_id=view.evidence_id,
        files_read_count=view.files_read_count,
        files_changed_count=view.files_changed_count,
        commands_count=view.commands_count,
        result=view.result,
        created_at=view.created_at,
    )


@router.get("/worker-runs/{worker_run_id}", response_model=WorkerRunDetailResponse)
async def get_worker_run(worker_run_id: str, request: Request) -> WorkerRunDetailResponse:
    services = _get_services(request)
    view = await run_in_threadpool(services.get_worker_run_detail.get, worker_run_id)
    return WorkerRunDetailResponse(
        worker_run_id=view.worker_run_id,
        task_id=view.task_id,
        status=view.status,
        created_at=view.created_at,
        started_at=view.started_at,
        finished_at=view.finished_at,
        energy=_energy_schema(view.energy),
        evidence=[_evidence_schema(e) for e in view.evidence],
    )
