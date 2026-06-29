"""CompletionFinalizer — terminal business mutation *outside* the graph (MICRO #4).

PHASE_4_PLAN C.7: graph terminal nodes only emit a ``final_outcome`` marker; this
finalizer applies the terminal Task/WorkflowRun statuses in one unit of work, keyed
by a deterministic ``completion_operation_id`` and guarded by CAS so a replay after a
crash (window #7) never double-applies and a COMPLETED never overwrites a CANCELLED.
It works whether or not an approval/ResumeOperation was ever involved.
"""

from __future__ import annotations

from collections.abc import Mapping

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
    """Applies terminal Task/WorkflowRun statuses idempotently (PHASE_4_PLAN C.7).

    CP5: optional ``terminal_handoff`` service creates a terminal handoff AFTER the UoW
    commits.  This is a recoverable two-phase sequence: if the handoff write fails the
    finalizer propagates the error (does not report success).  On replay the UoW CAS is a
    no-op (already terminal) and the handoff service reuses the existing record.
    """

    def __init__(
        self,
        uow_factory: UnitOfWorkFactory,
        *,
        clock: Clock,
        ids: IdGenerator,
        terminal_handoff: object | None = None,
        task_result_finalizer: object | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids
        self._terminal_handoff = terminal_handoff
        self._task_result_finalizer = task_result_finalizer

    def finalize(
        self,
        run_id: WorkflowRunId,
        *,
        final_outcome: str | None,
        checkpoint_id: str | None,
        resume_operation_id: str | None = None,
        state: Mapping[str, object] | None = None,
    ) -> WorkflowOutcome:
        """Finalize the run/task terminal statuses; return the framework-neutral outcome.

        Phase 1 (UoW): CAS workflow-run + task status + transitions atomically.
        Phase 2 (post-UoW): create terminal handoff if service is configured.  If the
        handoff write fails, the error propagates — the caller should NOT treat this as a
        successful completion.  On replay phase 1 is a CAS no-op; phase 2 reuses the
        existing handoff record (idempotent by deterministic ``HandoffId``).
        """
        if final_outcome is None or checkpoint_id is None:
            raise CheckpointRecoveryError("completion requires a final outcome and checkpoint id")
        mapping = _OUTCOME_MAP.get(final_outcome)
        if mapping is None:
            raise CheckpointRecoveryError(f"unknown final outcome: {final_outcome}")
        run_status, task_status, trigger = mapping

        # Phase 1: atomic status transition.
        task_id_str: str | None = None
        with self._uow_factory() as uow:
            run = uow.workflow_runs.get(run_id)
            task_id_str = run.task_id.value
            if not run.status.is_terminal:
                now = self._clock.now()
                op_id = completion_operation_id(run_id.value, checkpoint_id)
                applied = uow.workflow_runs.compare_and_set_status(
                    run.with_checkpoint_observed(checkpoint_id, now=now).with_status(
                        run_status, now=now
                    ),
                    expected=run.status,
                )
                if applied:
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

        # Phase 2: terminal handoff (fail-closed: error propagates if write fails).
        if self._terminal_handoff is not None and task_id_str is not None:
            from ant_orchestrator.application.services.terminal_handoff import (
                TerminalHandoffService,
            )

            if isinstance(self._terminal_handoff, TerminalHandoffService):
                self._terminal_handoff.create_terminal_handoff(
                    run_id=run_id.value,
                    task_id=task_id_str,
                    final_outcome=final_outcome,
                    state=state or {},
                )

        # Phase 3: task result persistence (fail-closed: error propagates if write fails).
        if self._task_result_finalizer is not None and task_id_str is not None:
            from ant_orchestrator.application.services.result_finalizer import (
                TaskResultFinalizer,
            )

            if isinstance(self._task_result_finalizer, TaskResultFinalizer):
                self._task_result_finalizer.finalize(
                    run_id=run_id.value,
                    task_id=task_id_str,
                    final_outcome=final_outcome,
                    state=state or {},
                )

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
