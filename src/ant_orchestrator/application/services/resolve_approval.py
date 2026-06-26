"""ResolveApproval — APPROVE / REJECT a pending approval gate (PHASE_4_PLAN C.5b/C.7).

UoW ordering (all in one transaction — PHASE_4_PLAN MICRO #3/PATCH #5):
  validate task/run/approval → acquire ResumeOperation (CAS owner_token)
  → resolve Approval (row_version CAS) → WorkflowRun→RUNNING → Task→RUNNING
  → append run/task/approval transitions → commit
  → (only owner) runner.resume({interrupt_id: decision})
  → CompletionFinalizer (END reached) or PauseFinalizer (graph interrupted again).

Idempotent retry (PHASE_4_PLAN MICRO #2):
  ResumeOperation already COMPLETED  → return terminal outcome without re-resuming.
  ResumeOperation OWNED by another   → return current run status without resuming.
  Decision conflicts with stored one → raise ApprovalStateConflict.
"""

from __future__ import annotations

from datetime import timedelta

from ant_orchestrator.application.errors import ApprovalRuleViolation, ApprovalStateConflict
from ant_orchestrator.application.ports.workflow_runner import WorkflowRunnerPort
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    WorkflowOutcome,
    append_transition,
)
from ant_orchestrator.config.constants import RESUME_LEASE_SECONDS
from ant_orchestrator.core.domain.enums import (
    ActorSource,
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
from ant_orchestrator.core.domain.workflow import ResumeOperation
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.unit_of_work import UnitOfWorkRepositories

_DECISION_TRIGGER: dict[ApprovalStatus, TransitionTrigger] = {
    ApprovalStatus.APPROVED: TransitionTrigger.APPROVE,
    ApprovalStatus.REJECTED: TransitionTrigger.REJECT,
}


class ResolveApproval:
    """Resolves a pending approval and drives the graph resume as the owner lease."""

    def __init__(
        self,
        runner: WorkflowRunnerPort,
        uow_factory: UnitOfWorkFactory,
        completion_finalizer: CompletionFinalizer,
        pause_finalizer: PauseFinalizer,
        *,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._runner = runner
        self._uow_factory = uow_factory
        self._completion_finalizer = completion_finalizer
        self._pause_finalizer = pause_finalizer
        self._clock = clock
        self._ids = ids

    def approve(
        self,
        task_id_value: str,
        *,
        actor_source: ActorSource | None = None,
        actor_label: str | None = None,
    ) -> WorkflowOutcome:
        """Approve the pending gate and resume the graph on the approved continuation."""
        return self._resolve(
            task_id_value,
            ApprovalStatus.APPROVED,
            actor_source=actor_source,
            actor_label=actor_label,
        )

    def reject(
        self,
        task_id_value: str,
        *,
        reason: str | None = None,
        actor_source: ActorSource | None = None,
        actor_label: str | None = None,
    ) -> WorkflowOutcome:
        """Reject the pending gate; the graph routes to the terminal rejected node."""
        return self._resolve(
            task_id_value,
            ApprovalStatus.REJECTED,
            reason=reason,
            actor_source=actor_source,
            actor_label=actor_label,
        )

    # ------------------------------------------------------------------
    # internal
    # ------------------------------------------------------------------

    def _resolve(
        self,
        task_id_value: str,
        decision: ApprovalStatus,
        *,
        reason: str | None = None,
        actor_source: ActorSource | None = None,
        actor_label: str | None = None,
    ) -> WorkflowOutcome:
        task_id = TaskId(task_id_value)
        now = self._clock.now()

        # Variables captured inside the UoW block (Python with-scope is not a new scope).
        thread_id: str = ""
        interrupt_id: str = ""
        op_id: str = ""
        is_owner = False
        run_id_captured: WorkflowRunId | None = None

        with self._uow_factory() as uow:
            task = uow.tasks.get(task_id)
            active_run = uow.workflow_runs.find_active_by_task(task_id)

            if active_run is None:
                if task.status.is_terminal:
                    # Idempotent: task already terminal (PHASE_4_PLAN MICRO #2).
                    return WorkflowOutcome(status=task.status.value, run_id="")
                raise ApprovalRuleViolation(f"task {task_id_value} has no active workflow run")
            if active_run.status != WorkflowRunStatus.AWAITING_APPROVAL:
                raise ApprovalRuleViolation(
                    f"run {active_run.id.value} is {active_run.status.value}, "
                    "expected awaiting_approval"
                )

            approval = uow.approvals.find_pending_by_run(active_run.id)
            if approval is None:
                raise ApprovalRuleViolation(
                    f"no pending approval found for run {active_run.id.value}"
                )

            existing_op = uow.resume_operations.find_by_approval(approval.id)
            run_id_captured = active_run.id
            thread_id = active_run.thread_id

            if existing_op is not None:
                if existing_op.decision != decision:
                    raise ApprovalStateConflict(
                        f"approval {approval.id.value} already has decision "
                        f"{existing_op.decision.value}; cannot apply {decision.value}"
                    )
                if existing_op.status == ResumeOperationStatus.COMPLETED:
                    is_owner = False  # Already finalized; idempotent return below.
                else:
                    is_owner = False  # Another process owns this lease.
                op_id = existing_op.id.value
                interrupt_id = existing_op.langgraph_interrupt_id or ""
            else:
                # Fresh acquire: become owner.
                op_id = self._ids.new_id()
                interrupt_id = approval.langgraph_interrupt_id or ""
                lease_expires = UtcTimestamp(now.value + timedelta(seconds=RESUME_LEASE_SECONDS))
                resume_op = ResumeOperation(
                    id=ResumeOperationId(op_id),
                    workflow_run_id=active_run.id,
                    approval_id=approval.id,
                    decision=decision,
                    status=ResumeOperationStatus.OWNED,
                    created_at=now,
                    langgraph_checkpoint_id=approval.langgraph_checkpoint_id,
                    langgraph_interrupt_id=approval.langgraph_interrupt_id,
                    owner_token=self._ids.new_id(),
                    lease_expires_at=lease_expires,
                )
                uow.resume_operations.add(resume_op)

                resolved = approval.resolve(
                    decision,
                    decided_at=now,
                    reason=reason,
                    actor_source=actor_source,
                    actor_label=actor_label,
                )
                ok = uow.approvals.resolve_with_version(
                    resolved, expected_version=approval.approval_row_version
                )
                if not ok:
                    raise ApprovalStateConflict("approval was resolved concurrently")

                trigger = _DECISION_TRIGGER[decision]
                uow.workflow_runs.update(active_run.with_status(WorkflowRunStatus.RUNNING, now=now))
                uow.tasks.update(task.with_status(TaskStatus.RUNNING, now=now))
                append_transition(
                    uow.transitions,
                    ids=self._ids,
                    now=now,
                    run_id=active_run.id,
                    subject=TransitionSubject.RUN,
                    to_status=WorkflowRunStatus.RUNNING.value,
                    trigger=trigger,
                    operation_id=op_id,
                    from_status=WorkflowRunStatus.AWAITING_APPROVAL.value,
                )
                append_transition(
                    uow.transitions,
                    ids=self._ids,
                    now=now,
                    run_id=active_run.id,
                    subject=TransitionSubject.TASK,
                    to_status=TaskStatus.RUNNING.value,
                    trigger=trigger,
                    operation_id=op_id,
                )
                append_transition(
                    uow.transitions,
                    ids=self._ids,
                    now=now,
                    run_id=active_run.id,
                    subject=TransitionSubject.APPROVAL,
                    to_status=resolved.status.value,
                    trigger=trigger,
                    operation_id=op_id,
                )
                is_owner = True

        assert run_id_captured is not None

        if not is_owner:
            return self._fetch_outcome(run_id_captured, resume_operation_id=op_id)

        # Owner: drive the graph resume and finalize.
        result = self._runner.resume(
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            decision=decision.value,
        )
        if result.interrupt is not None:
            # Graph interrupted again (e.g. RetryGrant → more executes → new gate).
            approval_id = self._pause_finalizer.finalize(
                run_id_captured, result.interrupt, checkpoint_id=result.checkpoint_id
            )
            self._settle_resume_op(op_id)
            return WorkflowOutcome(
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                run_id=run_id_captured.value,
                approval_id=approval_id,
                resume_operation_id=op_id,
            )
        return self._completion_finalizer.finalize(
            run_id_captured,
            final_outcome=result.final_outcome,
            checkpoint_id=result.checkpoint_id,
            resume_operation_id=op_id,
        )

    def _settle_resume_op(self, resume_operation_id: str) -> None:
        """Mark a ResumeOperation COMPLETED in a dedicated UoW."""
        now = self._clock.now()
        with self._uow_factory() as uow:
            self._settle_op(uow, resume_operation_id, now)

    @staticmethod
    def _settle_op(
        uow: UnitOfWorkRepositories, resume_operation_id: str, now: UtcTimestamp
    ) -> None:
        op = uow.resume_operations.get(ResumeOperationId(resume_operation_id))
        if op.status is not ResumeOperationStatus.COMPLETED:
            uow.resume_operations.update(
                op.with_status(ResumeOperationStatus.COMPLETED, completed_at=now)
            )

    def _fetch_outcome(self, run_id: WorkflowRunId, *, resume_operation_id: str) -> WorkflowOutcome:
        """Return the current task status without driving the graph (non-owner / idempotent)."""
        with self._uow_factory() as uow:
            run = uow.workflow_runs.get(run_id)
            task = uow.tasks.get(run.task_id)
        return WorkflowOutcome(
            status=task.status.value,
            run_id=run_id.value,
            resume_operation_id=resume_operation_id,
            resumed=True,
        )
