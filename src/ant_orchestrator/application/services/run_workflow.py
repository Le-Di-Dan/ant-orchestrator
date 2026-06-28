"""RunWorkflow — start a graph execution or re-enter a paused run (PHASE_4_PLAN C.5).

Happy path: create WorkflowRun + transition in one UoW → invoke graph → dispatch to
PauseFinalizer (interrupted) or CompletionFinalizer (END reached).

Re-entry paths:
  AWAITING_APPROVAL  → find existing Approval and return AWAITING_APPROVAL (idempotent);
                       if Approval is missing, re-finalize from the durable snapshot (crash #2).
  RUNNING + no-checkpoint-observed → re-invoke from START (crash #1 recovery).
  RUNNING + interrupted snapshot   → re-finalize PauseFinalizer (crash #2 variant).
  RUNNING + END snapshot           → re-finalize CompletionFinalizer (crash #7 variant).
  RUNNING + checkpoint observed + unclear state → fail closed (Scenario H).
"""

from __future__ import annotations

from ant_orchestrator.application.errors import CheckpointRecoveryError, WorkflowStateError
from ant_orchestrator.application.ports.documentation_execution import (
    WorkflowDocumentationPreparer,
)
from ant_orchestrator.application.ports.workflow_runner import WorkflowRunnerPort
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    WorkflowOutcome,
    append_transition,
    thread_id_for,
)
from ant_orchestrator.config.constants import (
    WORKFLOW_DEFINITION_VERSION,
    WORKFLOW_MAX_RETRIES,
)
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import (
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import TaskId, WorkflowRunId
from ant_orchestrator.core.domain.workflow import WorkflowRun
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator


class RunWorkflow:
    """Drives a full workflow execution from task-id to a terminal or paused outcome."""

    def __init__(
        self,
        runner: WorkflowRunnerPort,
        uow_factory: UnitOfWorkFactory,
        pause_finalizer: PauseFinalizer,
        completion_finalizer: CompletionFinalizer,
        *,
        clock: Clock,
        ids: IdGenerator,
        documentation_preparer: WorkflowDocumentationPreparer | None = None,
    ) -> None:
        self._runner = runner
        self._uow_factory = uow_factory
        self._pause_finalizer = pause_finalizer
        self._completion_finalizer = completion_finalizer
        self._clock = clock
        self._ids = ids
        self._documentation_preparer = documentation_preparer

    def execute(self, task_id_value: str) -> WorkflowOutcome:
        """Run or re-enter the workflow for the given task."""
        task_id = TaskId(task_id_value)

        with self._uow_factory() as uow:
            task = uow.tasks.get(task_id)
            active_run = uow.workflow_runs.find_active_by_task(task_id)

        if task.status.is_terminal:
            raise WorkflowStateError(
                f"task {task_id_value} is already terminal ({task.status.value})"
            )

        if active_run is not None:
            return self._handle_existing_run(active_run)

        return self._create_and_invoke(task_id, task)

    # ------------------------------------------------------------------
    # internal helpers
    # ------------------------------------------------------------------

    def _create_and_invoke(self, task_id: TaskId, task: Task) -> WorkflowOutcome:
        """Create WorkflowRun + transitions in UoW, then invoke the graph."""
        run_id = WorkflowRunId(self._ids.new_id())
        now = self._clock.now()
        invoke_op_id = f"invoke-{run_id.value}"
        thread_id = thread_id_for(run_id.value)

        # Phase 5 CP6: prepare context + proposal BEFORE the run is created so a scope/identity
        # failure fails closed with no orphan run. A non-documentation task returns no extras.
        extras: dict[str, object] = {}
        if self._documentation_preparer is not None:
            prepared = self._documentation_preparer.prepare_initial_state(run_id.value, task)
            if prepared is not None:
                extras = dict(prepared)

        run = WorkflowRun(
            id=run_id,
            task_id=task_id,
            thread_id=thread_id,
            status=WorkflowRunStatus.RUNNING,
            workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
            initial_invoke_operation_id=invoke_op_id,
            created_at=now,
            updated_at=now,
        )

        with self._uow_factory() as uow:
            task_obj = uow.tasks.get(task_id)
            uow.workflow_runs.add(run)
            uow.tasks.update(task_obj.with_status(TaskStatus.RUNNING, now=now))
            append_transition(
                uow.transitions,
                ids=self._ids,
                now=now,
                run_id=run_id,
                subject=TransitionSubject.RUN,
                to_status=WorkflowRunStatus.RUNNING.value,
                trigger=TransitionTrigger.RUN_CREATED,
                operation_id=invoke_op_id,
            )
            append_transition(
                uow.transitions,
                ids=self._ids,
                now=now,
                run_id=run_id,
                subject=TransitionSubject.TASK,
                to_status=TaskStatus.RUNNING.value,
                trigger=TransitionTrigger.RUN_CREATED,
                operation_id=f"{invoke_op_id}-task",
            )

        return self._invoke_and_finalize(run_id, thread_id, task_id, extras=extras)

    def _invoke_and_finalize(
        self,
        run_id: WorkflowRunId,
        thread_id: str,
        task_id: TaskId,
        *,
        extras: dict[str, object] | None = None,
    ) -> WorkflowOutcome:
        """Invoke the graph and dispatch to the appropriate finalizer."""
        initial_state = self._runner.build_initial_state(
            task_id=task_id.value,
            workflow_run_id=run_id.value,
            base_retry_limit=WORKFLOW_MAX_RETRIES,
        )
        if extras:
            initial_state.update(extras)
        result = self._runner.invoke(initial_state, thread_id=thread_id)

        if result.interrupt is not None:
            approval_id = self._pause_finalizer.finalize(
                run_id, result.interrupt, checkpoint_id=result.checkpoint_id
            )
            return WorkflowOutcome(
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                run_id=run_id.value,
                approval_id=approval_id,
            )

        return self._completion_finalizer.finalize(
            run_id,
            final_outcome=result.final_outcome,
            checkpoint_id=result.checkpoint_id,
            state=result.final_state,
        )

    def _handle_existing_run(self, run: WorkflowRun) -> WorkflowOutcome:
        """Re-enter or recover an existing active run."""
        # Fail closed before any re-invoke/resume/finalize if this run was created under
        # an incompatible workflow-definition version (CP8 re-entry version guard).
        self._runner.check_definition_version(run.workflow_definition_version)

        if run.status == WorkflowRunStatus.AWAITING_APPROVAL:
            return self._re_enter_awaiting(run)

        # RUNNING: inspect the durable snapshot to determine the crash window.
        summary = self._runner.latest_state(run.thread_id)
        self._runner.check_state_schema(summary.values)

        if summary.is_interrupted:
            # Crash #2: checkpoint is durable + interrupted, but PauseFinalizer never ran.
            interrupt = summary.interrupts[0]
            approval_id = self._pause_finalizer.finalize(
                run.id, interrupt, checkpoint_id=summary.checkpoint_id
            )
            return WorkflowOutcome(
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                run_id=run.id.value,
                approval_id=approval_id,
            )

        final_outcome_raw = summary.values.get("final_outcome") if summary.values else None
        if len(summary.next_nodes) == 0 and final_outcome_raw:
            # Crash #7: END checkpoint is durable but CompletionFinalizer never ran.
            return self._completion_finalizer.finalize(
                run.id,
                final_outcome=str(final_outcome_raw),
                checkpoint_id=summary.checkpoint_id,
                state=summary.values,
            )

        # No snapshot yet (empty graph thread) → crash #1: safe to re-invoke from START.
        if run.checkpoint_ever_observed:
            raise CheckpointRecoveryError(
                f"run {run.id.value} has an observed checkpoint but graph state is unclear "
                f"(Scenario H — manual recovery required)"
            )
        return self._invoke_and_finalize(run.id, run.thread_id, run.task_id)

    def _re_enter_awaiting(self, run: WorkflowRun) -> WorkflowOutcome:
        """Return AWAITING_APPROVAL if Approval exists; re-finalize if it is missing."""
        with self._uow_factory() as uow:
            approval = uow.approvals.find_pending_by_run(run.id)

        if approval is not None:
            return WorkflowOutcome(
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                run_id=run.id.value,
                approval_id=approval.id.value,
            )

        # Approval missing (crash #2 variant): re-finalize from the durable snapshot.
        summary = self._runner.latest_state(run.thread_id)
        self._runner.check_state_schema(summary.values)
        if not summary.is_interrupted:
            raise CheckpointRecoveryError(
                f"run {run.id.value} is AWAITING_APPROVAL but the graph snapshot is not interrupted"
            )
        interrupt = summary.interrupts[0]
        approval_id = self._pause_finalizer.finalize(
            run.id, interrupt, checkpoint_id=summary.checkpoint_id
        )
        return WorkflowOutcome(
            status=TaskStatus.WAITING_FOR_APPROVAL.value,
            run_id=run.id.value,
            approval_id=approval_id,
        )
