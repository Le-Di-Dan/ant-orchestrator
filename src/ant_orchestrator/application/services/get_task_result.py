"""GetTaskResult — application service for retrieving a finalized task result (CP4).

Distinguishes three cases:
- Result is ready: returns TaskResultView.
- Task exists but result is not final yet: returns None (caller interprets as pending).
- Task does not exist: raises RecordNotFound.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ant_orchestrator.application.models.result_views import (
    ArtifactRefView,
    FailureInfoView,
    TaskResultView,
)
from ant_orchestrator.core.domain.task_result import ArtifactRef, FailureInfo, TaskResult
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.core.ports.repositories import TaskRepository

__all__ = ["GetTaskResult", "TaskResultRepository"]


@runtime_checkable
class TaskResultRepository(Protocol):
    """Minimal read port for task result retrieval (application-layer view)."""

    def find_by_task(self, task_id: str) -> TaskResult | None: ...


class GetTaskResult:
    """Return the finalized result for a task, or None if not yet complete."""

    def __init__(
        self,
        task_repo: TaskRepository,
        result_repo: TaskResultRepository,
    ) -> None:
        self._tasks = task_repo
        self._results = result_repo

    def get(self, task_id_value: str) -> TaskResultView | None:
        """Return the TaskResultView, None if pending, or raise RecordNotFound."""
        task_id = TaskId(task_id_value)
        self._tasks.get(task_id)  # raises RecordNotFound if task absent
        result = self._results.find_by_task(task_id_value)
        if result is None:
            return None
        return _to_view(result)


def _to_view(result: TaskResult) -> TaskResultView:
    return TaskResultView(
        result_id=result.result_id.value,
        task_id=result.task_id,
        workflow_run_id=result.workflow_run_id,
        outcome=result.outcome.value,
        summary=result.summary,
        artifact_refs=tuple(_artifact_view(a) for a in result.artifact_refs),
        failure=_failure_view(result.failure) if result.failure is not None else None,
        finalized_at=result.finalized_at.to_iso(),
        result_version=result.result_version,
    )


def _artifact_view(ref: ArtifactRef) -> ArtifactRefView:
    return ArtifactRefView(
        artifact_id=ref.artifact_id,
        kind=ref.kind.value,
        relative_path=ref.relative_path,
        media_type=ref.media_type,
        sha256=ref.sha256,
        size_bytes=ref.size_bytes,
        created_by_attempt_id=ref.created_by_attempt_id,
        state=ref.state.value,
        metadata=ref.metadata,
    )


def _failure_view(failure: FailureInfo) -> FailureInfoView:
    return FailureInfoView(
        code=failure.code,
        message=failure.message,
        retryable=failure.retryable,
        source=failure.source,
    )
