"""CancelTask — cooperative cancellation across CREATED, AWAITING_APPROVAL, RUNNING (CP6).

CREATED:          Task → CANCELLED in one UoW; no WorkflowRun, no graph invocation.
AWAITING_APPROVAL: acquire ResumeOperation → resolve Approval = CANCELLED (row-version CAS)
                  → transition states in UoW → resume graph as owner with CANCEL decision
                  → CompletionFinalizer writes terminal CANCELLED statuses.
RUNNING:          set WorkflowRun.cancel_requested_at (idempotent) → return CANCEL_REQUESTED
                  immediately; caller polls/reconciles for the eventual terminal state.

All paths are idempotent: re-issuing a cancel on an already-terminal task or an already-
cancelled approval returns the current terminal status without side effects.
"""

from __future__ import annotations

from datetime import timedelta

from ant_orchestrator.application.errors import ApprovalStateConflict, WorkflowStateError
from ant_orchestrator.application.ports.workflow_runner import WorkflowRunnerPort
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    WorkflowOutcome,
    append_transition,
    latest_persisted_decision,
)
from ant_orchestrator.config.constants import (
    CANCEL_REQUEST_OPERATION_PREFIX,
    CANCEL_REQUESTED_STATUS,
    RESUME_LEASE_SECONDS,
)
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ResumeOperationStatus,
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    ResumeOperationId,
    TaskId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ResumeOperation, WorkflowRun
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.unit_of_work import UnitOfWorkRepositories


class CancelTask:
    """Application use case: cooperative cancellation for all pre-terminal task states."""

    def __init__(
        self,
        runner: WorkflowRunnerPort,
        uow_factory: UnitOfWorkFactory,
        completion_finalizer: CompletionFinalizer,
        *,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._runner = runner
        self._uow_factory = uow_factory
        self._completion_finalizer = completion_finalizer
        self._clock = clock
        self._ids = ids

    def cancel(self, task_id_value: str) -> WorkflowOutcome:
        """Cancel the task; dispatch to the correct strategy based on its current state."""
        task_id = TaskId(task_id_value)

        with self._uow_factory() as uow:
            task = uow.tasks.get(task_id)
            active_run = uow.workflow_runs.find_active_by_task(task_id)
            decided = latest_persisted_decision(uow.approvals.list_by_task(task_id))

        if task.status.is_terminal:
            # A different persisted decision (approved/rejected) cannot be re-cancelled.
            if decided is not None and decided is not ApprovalStatus.CANCELLED:
                raise ApprovalStateConflict(
                    f"task {task_id_value} already resolved as {decided.value}; "
                    "cannot apply cancelled"
                )
            return WorkflowOutcome(status=task.status.value, run_id="")

        if active_run is None:
            return self._cancel_created(task_id)

        if active_run.status == WorkflowRunStatus.AWAITING_APPROVAL:
            return self._cancel_awaiting(task_id, active_run)

        return self._cancel_running(active_run)

    # ------------------------------------------------------------------
    # CREATED — no WorkflowRun; transition task directly
    # ------------------------------------------------------------------

    def _cancel_created(self, task_id: TaskId) -> WorkflowOutcome:
        now = self._clock.now()
        with self._uow_factory() as uow:
            task = uow.tasks.get(task_id)
            if task.status.is_terminal:
                return WorkflowOutcome(status=task.status.value, run_id="")
            uow.tasks.update(task.with_status(TaskStatus.CANCELLED, now=now))
        return WorkflowOutcome(status=TaskStatus.CANCELLED.value, run_id="")

    # ------------------------------------------------------------------
    # AWAITING_APPROVAL — resolve Approval + resume graph via CANCEL decision
    # ------------------------------------------------------------------

    def _cancel_awaiting(self, task_id: TaskId, active_run: WorkflowRun) -> WorkflowOutcome:
        now = self._clock.now()
        run_id = active_run.id
        thread_id: str = active_run.thread_id
        interrupt_id: str = ""
        op_id: str = ""
        is_owner = False

        with self._uow_factory() as uow:
            task = uow.tasks.get(task_id)
            approval = uow.approvals.find_pending_by_run(run_id)
            if approval is None:
                raise WorkflowStateError(f"no pending approval found for run {run_id.value}")

            # Fail closed before mutating the Approval/ResumeOperation if the run was
            # created under an incompatible workflow-definition version (CP8 guard).
            self._runner.check_definition_version(active_run.workflow_definition_version)

            existing_op = uow.resume_operations.find_by_approval(approval.id)

            if existing_op is not None:
                if existing_op.decision != ApprovalStatus.CANCELLED:
                    raise ApprovalStateConflict(
                        f"approval {approval.id.value} already has decision "
                        f"{existing_op.decision.value}; cannot apply cancelled"
                    )
                op_id = existing_op.id.value
                interrupt_id = existing_op.langgraph_interrupt_id or ""
                is_owner = existing_op.status is not ResumeOperationStatus.COMPLETED
            else:
                op_id = self._ids.new_id()
                interrupt_id = approval.langgraph_interrupt_id or ""
                lease_expires = UtcTimestamp(now.value + timedelta(seconds=RESUME_LEASE_SECONDS))
                resume_op = ResumeOperation(
                    id=ResumeOperationId(op_id),
                    workflow_run_id=run_id,
                    approval_id=approval.id,
                    decision=ApprovalStatus.CANCELLED,
                    status=ResumeOperationStatus.OWNED,
                    created_at=now,
                    langgraph_checkpoint_id=approval.langgraph_checkpoint_id,
                    langgraph_interrupt_id=approval.langgraph_interrupt_id,
                    owner_token=self._ids.new_id(),
                    lease_expires_at=lease_expires,
                )
                uow.resume_operations.add(resume_op)

                resolved = approval.resolve(ApprovalStatus.CANCELLED, decided_at=now)
                ok = uow.approvals.resolve_with_version(
                    resolved, expected_version=approval.approval_row_version
                )
                if not ok:
                    raise ApprovalStateConflict("approval was resolved concurrently")

                uow.workflow_runs.update(active_run.with_status(WorkflowRunStatus.RUNNING, now=now))
                uow.tasks.update(task.with_status(TaskStatus.RUNNING, now=now))
                self._append_cancel_transitions(uow, run_id, op_id, active_run.status, now)
                is_owner = True

        return self._drive_cancel_resume(run_id, thread_id, interrupt_id, op_id, is_owner)

    def _append_cancel_transitions(
        self,
        uow: UnitOfWorkRepositories,
        run_id: WorkflowRunId,
        op_id: str,
        from_run_status: WorkflowRunStatus,
        now: UtcTimestamp,
    ) -> None:
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.RUN,
            to_status=WorkflowRunStatus.RUNNING.value,
            trigger=TransitionTrigger.CANCEL,
            operation_id=op_id,
            from_status=from_run_status.value,
        )
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.TASK,
            to_status=TaskStatus.RUNNING.value,
            trigger=TransitionTrigger.CANCEL,
            operation_id=op_id,
        )
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.APPROVAL,
            to_status=ApprovalStatus.CANCELLED.value,
            trigger=TransitionTrigger.CANCEL,
            operation_id=op_id,
        )

    def _drive_cancel_resume(
        self,
        run_id: WorkflowRunId,
        thread_id: str,
        interrupt_id: str,
        op_id: str,
        is_owner: bool,
    ) -> WorkflowOutcome:
        if not is_owner:
            with self._uow_factory() as uow:
                run = uow.workflow_runs.get(run_id)
                task = uow.tasks.get(run.task_id)
            return WorkflowOutcome(status=task.status.value, run_id=run_id.value)

        result = self._runner.resume(
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            decision=ApprovalStatus.CANCELLED.value,
        )
        return self._completion_finalizer.finalize(
            run_id,
            final_outcome=result.final_outcome,
            checkpoint_id=result.checkpoint_id,
            resume_operation_id=op_id,
        )

    # ------------------------------------------------------------------
    # RUNNING — set cancel flag; graph probes it at next effectful boundary
    # ------------------------------------------------------------------

    def _cancel_running(self, active_run: WorkflowRun) -> WorkflowOutcome:
        run_id = active_run.id
        now = self._clock.now()
        op_id = f"{CANCEL_REQUEST_OPERATION_PREFIX}{run_id.value}"

        with self._uow_factory() as uow:
            current = uow.workflow_runs.get(run_id)
            if current.cancel_requested_at is not None:
                return WorkflowOutcome(status=CANCEL_REQUESTED_STATUS, run_id=run_id.value)
            uow.workflow_runs.update(current.with_cancel_requested(now=now))
            append_transition(
                uow.transitions,
                ids=self._ids,
                now=now,
                run_id=run_id,
                subject=TransitionSubject.RUN,
                to_status=CANCEL_REQUESTED_STATUS,
                trigger=TransitionTrigger.CANCEL_REQUEST,
                operation_id=op_id,
            )

        return WorkflowOutcome(status=CANCEL_REQUESTED_STATUS, run_id=run_id.value)
