"""Reconciler — detect and repair crash windows #2 and #7 (PHASE_4_PLAN E.3).

Crash #2: WorkflowRun RUNNING, durable checkpoint is interrupted, but PauseFinalizer
          never committed (graph paused but no Approval row in the DB).
          → Re-run PauseFinalizer idempotently; never resume the graph.

Crash #7: WorkflowRun RUNNING, durable checkpoint has reached END, but
          CompletionFinalizer never committed.
          → Re-run CompletionFinalizer idempotently (stable operation_id, CAS guard).

Both methods are safe to call speculatively: they return ``None`` when no action is
needed. The Reconciler does NOT resolve approvals or drive graph resumes — it only
persists business state that should already have been written.
"""

from __future__ import annotations

from ant_orchestrator.application.errors import CheckpointRecoveryError
from ant_orchestrator.application.ports.workflow_runner import WorkflowRunnerPort
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    WorkflowOutcome,
)
from ant_orchestrator.core.domain.enums import TaskStatus, WorkflowRunStatus
from ant_orchestrator.core.domain.value_objects import TaskId, WorkflowRunId


class Reconciler:
    """Detects and repairs RUNNING workflow runs stuck in crash windows #2 or #7."""

    def __init__(
        self,
        runner: WorkflowRunnerPort,
        uow_factory: UnitOfWorkFactory,
        pause_finalizer: PauseFinalizer,
        completion_finalizer: CompletionFinalizer,
    ) -> None:
        self._runner = runner
        self._uow_factory = uow_factory
        self._pause_finalizer = pause_finalizer
        self._completion_finalizer = completion_finalizer

    def reconcile_run(self, run_id: WorkflowRunId) -> WorkflowOutcome | None:
        """Reconcile one RUNNING run. Returns outcome if action was taken, else None."""
        with self._uow_factory() as uow:
            run = uow.workflow_runs.get(run_id)

        if run.status != WorkflowRunStatus.RUNNING:
            return None

        # Fail closed before any finalize/recovery if the run predates this topology.
        self._runner.check_definition_version(run.workflow_definition_version)

        summary = self._runner.latest_state(run.thread_id)
        self._runner.check_state_schema(summary.values)

        if summary.is_interrupted:
            # Crash #2: paused checkpoint exists but PauseFinalizer never ran.
            interrupt = summary.interrupts[0]
            approval_id = self._pause_finalizer.finalize(
                run.id, interrupt, checkpoint_id=summary.checkpoint_id
            )
            return WorkflowOutcome(
                status=TaskStatus.WAITING_FOR_APPROVAL.value,
                run_id=run_id.value,
                approval_id=approval_id,
            )

        final_outcome_raw = summary.values.get("final_outcome") if summary.values else None
        if len(summary.next_nodes) == 0 and final_outcome_raw:
            # Crash #7: END checkpoint is durable but CompletionFinalizer never ran.
            return self._completion_finalizer.finalize(
                run.id,
                final_outcome=str(final_outcome_raw),
                checkpoint_id=summary.checkpoint_id,
            )

        # No clear snapshot: distinguish initial invoke not done from lost checkpoint.
        if run.checkpoint_ever_observed:
            raise CheckpointRecoveryError(
                f"run {run_id.value}: checkpoint was observed but snapshot state is unclear "
                "(Scenario H — manual recovery required)"
            )

        return None  # No checkpoint observed: initial invoke not done; caller re-invokes.

    def reconcile_task(self, task_id_value: str) -> WorkflowOutcome | None:
        """Reconcile the active run for a task (if any). Returns outcome or None."""
        task_id = TaskId(task_id_value)

        with self._uow_factory() as uow:
            active_run = uow.workflow_runs.find_active_by_task(task_id)

        if active_run is None or active_run.status != WorkflowRunStatus.RUNNING:
            return None

        return self.reconcile_run(active_run.id)
