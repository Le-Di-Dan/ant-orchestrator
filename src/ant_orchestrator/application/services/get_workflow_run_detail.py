"""GetWorkflowRunDetail — full observable workflow-run read model (CP7)."""

from __future__ import annotations

from ant_orchestrator.application.models.execution_views import WorkflowRunDetailView
from ant_orchestrator.core.domain.value_objects import WorkflowRunId
from ant_orchestrator.core.ports.repositories import WorkflowRunRepository


class GetWorkflowRunDetail:
    """Application use case: build full workflow-run detail view."""

    def __init__(self, workflow_run_repo: WorkflowRunRepository) -> None:
        self._runs = workflow_run_repo

    def get(self, workflow_run_id_value: str) -> WorkflowRunDetailView:
        run_id = WorkflowRunId(workflow_run_id_value)
        run = self._runs.get(run_id)
        return WorkflowRunDetailView(
            workflow_run_id=run.id.value,
            task_id=run.task_id.value,
            status=run.status.value,
            workflow_definition_version=run.workflow_definition_version,
            created_at=run.created_at.to_iso(),
            updated_at=run.updated_at.to_iso(),
            cancel_requested=run.cancel_requested_at is not None,
        )
