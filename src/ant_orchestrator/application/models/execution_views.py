"""Immutable read-only views for task, worker-run, and energy observability (CP3)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EnergyTotalsView:
    """Aggregated token counts for a task or worker run."""

    tokens_in: int
    tokens_out: int
    record_count: int


@dataclass(frozen=True, slots=True)
class WorkflowRunSummaryView:
    """Minimal summary of a workflow-run execution cursor."""

    workflow_run_id: str
    status: str
    created_at: str
    updated_at: str
    cancel_requested: bool


@dataclass(frozen=True, slots=True)
class WorkerRunSummaryView:
    """Minimal summary of a worker-run execution entity."""

    worker_run_id: str
    task_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class ApprovalView:
    """Observable approval record (pending or resolved)."""

    approval_id: str
    status: str
    gate_type: str | None
    requested_at: str
    decided_at: str | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class TaskDetailView:
    """Full observable detail for one task (CP3 read model)."""

    task_id: str
    title: str
    status: str
    priority: str
    source: str
    created_at: str
    updated_at: str
    active_workflow_run: WorkflowRunSummaryView | None
    worker_runs: tuple[WorkerRunSummaryView, ...]
    energy_totals: EnergyTotalsView
    approvals: tuple[ApprovalView, ...]


@dataclass(frozen=True, slots=True)
class EvidenceSummaryView:
    """Compact summary of one execution evidence record."""

    evidence_id: str
    files_read_count: int
    files_changed_count: int
    commands_count: int
    result: str | None
    created_at: str


@dataclass(frozen=True, slots=True)
class WorkerRunDetailView:
    """Full observable detail for one worker run (CP3 read model)."""

    worker_run_id: str
    task_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    energy: EnergyTotalsView
    evidence: tuple[EvidenceSummaryView, ...]
