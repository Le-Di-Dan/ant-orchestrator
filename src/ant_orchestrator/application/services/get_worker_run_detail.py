"""GetWorkerRunDetail — full observable worker-run read model (CP3)."""

from __future__ import annotations

from ant_orchestrator.application.models.execution_views import (
    EnergyTotalsView,
    EvidenceSummaryView,
    WorkerRunDetailView,
)
from ant_orchestrator.config.constants import WORKER_RUN_DETAIL_EVIDENCE_LIMIT
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence
from ant_orchestrator.core.domain.value_objects import WorkerRunId
from ant_orchestrator.core.ports.repositories import (
    EnergyUsageRepository,
    ExecutionEvidenceRepository,
    WorkerRunRepository,
)


class GetWorkerRunDetail:
    """Application use case: build full worker-run detail view."""

    def __init__(
        self,
        worker_run_repo: WorkerRunRepository,
        energy_repo: EnergyUsageRepository,
        evidence_repo: ExecutionEvidenceRepository,
    ) -> None:
        self._worker_runs = worker_run_repo
        self._energy = energy_repo
        self._evidence = evidence_repo

    def get(self, worker_run_id_value: str) -> WorkerRunDetailView:
        worker_run_id = WorkerRunId(worker_run_id_value)
        run = self._worker_runs.get(worker_run_id)

        energy_list = list(self._energy.list_by_worker_run(worker_run_id))
        energy_totals = _aggregate_energy(energy_list)

        evidence_list = list(self._evidence.list_by_worker_run(worker_run_id))
        evidence_list.sort(key=lambda e: e.created_at.value)
        evidence_bounded = evidence_list[:WORKER_RUN_DETAIL_EVIDENCE_LIMIT]

        started = run.started_at.to_iso() if run.started_at is not None else None
        finished = run.finished_at.to_iso() if run.finished_at is not None else None

        return WorkerRunDetailView(
            worker_run_id=run.id.value,
            task_id=run.task_id.value,
            status=run.status.value,
            created_at=run.created_at.to_iso(),
            started_at=started,
            finished_at=finished,
            energy=energy_totals,
            evidence=tuple(_evidence_view(e) for e in evidence_bounded),
        )


def _aggregate_energy(records: list[EnergyUsage]) -> EnergyTotalsView:
    return EnergyTotalsView(
        tokens_in=sum(r.tokens_in.value for r in records),
        tokens_out=sum(r.tokens_out.value for r in records),
        record_count=len(records),
    )


def _evidence_view(e: ExecutionEvidence) -> EvidenceSummaryView:
    return EvidenceSummaryView(
        evidence_id=e.id.value,
        files_read_count=len(e.files_read),
        files_changed_count=len(e.files_changed),
        commands_count=len(e.commands),
        result=e.result,
        created_at=e.created_at.to_iso(),
    )
