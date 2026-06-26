"""CompletionFinalizer — terminal business mutation *outside* the graph (MICRO #4).

PHASE_4_PLAN C.7: graph terminal nodes only emit a ``final_outcome`` marker; this
finalizer applies the terminal Task/WorkflowRun statuses in one unit of work, keyed
by a deterministic ``completion_operation_id`` and guarded by CAS so a replay after a
crash (window #7) never double-applies and a COMPLETED never overwrites a CANCELLED.
It works whether or not an approval/ResumeOperation was ever involved.
"""

from __future__ import annotations

from ant_orchestrator.application.errors import CheckpointRecoveryError
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    WorkflowOutcome,
    append_transition,
    completion_operation_id,
)
from ant_orchestrator.core.domain.enums import (
    ResumeOperationStatus,
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    ResumeOperationId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.unit_of_work import UnitOfWorkRepositories

# final_outcome marker -> (run terminal status, task terminal status, transition trigger).
_OUTCOME_MAP: dict[str, tuple[WorkflowRunStatus, TaskStatus, TransitionTrigger]] = {
    "completed": (WorkflowRunStatus.COMPLETED, TaskStatus.COMPLETED, TransitionTrigger.COMPLETE),
    "failed": (WorkflowRunStatus.FAILED, TaskStatus.FAILED, TransitionTrigger.FAIL),
    "rejected": (WorkflowRunStatus.COMPLETED, TaskStatus.REJECTED, TransitionTrigger.REJECT),
    "cancelled": (WorkflowRunStatus.CANCELLED, TaskStatus.CANCELLED, TransitionTrigger.CANCEL),
}


class CompletionFinalizer:
    """Applies terminal Task/WorkflowRun statuses idempotently (PHASE_4_PLAN C.7)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    def finalize(
        self,
        run_id: WorkflowRunId,
        *,
        final_outcome: str | None,
        checkpoint_id: str | None,
        resume_operation_id: str | None = None,
    ) -> WorkflowOutcome:
        """Finalize the run/task terminal statuses; return the framework-neutral outcome."""
        if final_outcome is None or checkpoint_id is None:
            raise CheckpointRecoveryError("completion requires a final outcome and checkpoint id")
        mapping = _OUTCOME_MAP.get(final_outcome)
        if mapping is None:
            raise CheckpointRecoveryError(f"unknown final outcome: {final_outcome}")
        run_status, task_status, trigger = mapping
        with self._uow_factory() as uow:
            run = uow.workflow_runs.get(run_id)
            if run.status.is_terminal:
                return WorkflowOutcome(
                    status=task_status.value, run_id=run_id.value, final_outcome=final_outcome
                )
            now = self._clock.now()
            op_id = completion_operation_id(run_id.value, checkpoint_id)
            applied = uow.workflow_runs.compare_and_set_status(
                run.with_checkpoint_observed(checkpoint_id, now=now).with_status(
                    run_status, now=now
                ),
                expected=run.status,
            )
            if not applied:
                return WorkflowOutcome(
                    status=task_status.value, run_id=run_id.value, final_outcome=final_outcome
                )
            append_transition(
                uow.transitions,
                ids=self._ids,
                now=now,
                run_id=run_id,
                subject=TransitionSubject.RUN,
                to_status=run_status.value,
                trigger=trigger,
                operation_id=op_id,
                from_status=run.status.value,
            )
            task = uow.tasks.get(run.task_id)
            if not task.status.is_terminal:
                uow.tasks.compare_and_set_status(
                    task.with_status(task_status, now=now), expected=task.status
                )
                append_transition(
                    uow.transitions,
                    ids=self._ids,
                    now=now,
                    run_id=run_id,
                    subject=TransitionSubject.TASK,
                    to_status=task_status.value,
                    trigger=trigger,
                    operation_id=op_id,
                    from_status=task.status.value,
                )
            if resume_operation_id is not None:
                self._settle_resume(uow, resume_operation_id, now=now)
            return WorkflowOutcome(
                status=task_status.value, run_id=run_id.value, final_outcome=final_outcome
            )

    def _settle_resume(
        self, uow: UnitOfWorkRepositories, resume_operation_id: str, *, now: UtcTimestamp
    ) -> None:
        operation = uow.resume_operations.get(ResumeOperationId(resume_operation_id))
        if operation.status is ResumeOperationStatus.COMPLETED:
            return
        uow.resume_operations.update(
            operation.with_status(ResumeOperationStatus.COMPLETED, completed_at=now)
        )
