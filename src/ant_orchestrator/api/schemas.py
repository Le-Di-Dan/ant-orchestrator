"""Pydantic request/response schemas for the Phase 7 FastAPI surface.

All schemas are separate from application domain types. Domain views are explicitly
mapped to these schemas — never passed through directly.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

# ---------------------------------------------------------------------------
# Shared error envelope
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    type: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


# ---------------------------------------------------------------------------
# POST /tasks
# ---------------------------------------------------------------------------


class CreateTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    priority: str | None = None


class TaskCreatedResponse(BaseModel):
    task_id: str
    title: str
    status: str
    priority: str
    source: str
    created_at: str


# ---------------------------------------------------------------------------
# POST /tasks/{task_id}/workflow-runs
# ---------------------------------------------------------------------------


class WorkflowRunResponse(BaseModel):
    workflow_run_id: str
    status: str
    approval_id: str | None = None


# ---------------------------------------------------------------------------
# GET /tasks/{task_id}
# ---------------------------------------------------------------------------


class EnergyTotalsSchema(BaseModel):
    tokens_in: int
    tokens_out: int
    record_count: int


class WorkflowRunSummarySchema(BaseModel):
    workflow_run_id: str
    status: str
    created_at: str
    updated_at: str
    cancel_requested: bool


class WorkerRunSummarySchema(BaseModel):
    worker_run_id: str
    task_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None


class ApprovalSchema(BaseModel):
    approval_id: str
    status: str
    gate_type: str | None
    requested_at: str
    decided_at: str | None
    reason: str | None


class TaskDetailResponse(BaseModel):
    task_id: str
    title: str
    status: str
    priority: str
    source: str
    created_at: str
    updated_at: str
    active_workflow_run: WorkflowRunSummarySchema | None
    worker_runs: list[WorkerRunSummarySchema]
    energy_totals: EnergyTotalsSchema
    approvals: list[ApprovalSchema]


# ---------------------------------------------------------------------------
# GET /workflow-runs/{workflow_run_id}
# ---------------------------------------------------------------------------


class WorkflowRunDetailResponse(BaseModel):
    workflow_run_id: str
    task_id: str
    status: str
    workflow_definition_version: int
    created_at: str
    updated_at: str
    cancel_requested: bool


# ---------------------------------------------------------------------------
# GET /worker-runs/{worker_run_id}
# ---------------------------------------------------------------------------


class EvidenceSummarySchema(BaseModel):
    evidence_id: str
    files_read_count: int
    files_changed_count: int
    commands_count: int
    result: str | None
    created_at: str


class WorkerRunDetailResponse(BaseModel):
    worker_run_id: str
    task_id: str
    status: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    energy: EnergyTotalsSchema
    evidence: list[EvidenceSummarySchema]


# ---------------------------------------------------------------------------
# GET /logs
# ---------------------------------------------------------------------------


class LogEntrySchema(BaseModel):
    event_type: str
    created_at: str
    correlation_id: str
    task_id: str | None
    decision: str | None


class LogsResponse(BaseModel):
    entries: list[LogEntrySchema]
    resolved_limit: int
    has_more: bool
    corrupt_count: int
    files_scanned: int
