"""Composition + helpers for the CP8 test-only application-service driver.

Mirrors the production ``build_workflow_services`` wiring but lets a test inject a
``ScriptedStubAdapter`` and optional structured action-intent flags, so retry /
regroup / escalation / significant-write branches that the vanilla production stub
(always SUCCESS, no significant write) cannot reach are still driven through the
*real* services, SQLite state DB and file checkpointer. No production command,
flag or environment switch is introduced.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.application.services.cancel_task import CancelTask
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.create_task import CreateTask
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.resolve_approval import ResolveApproval
from ant_orchestrator.application.services.run_workflow import RunWorkflow
from ant_orchestrator.application.services.task_status import GetTaskStatus
from ant_orchestrator.application.services.workflow_support import WorkflowOutcome
from ant_orchestrator.cli.composition import SystemClock, Uuid4IdGenerator
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION, WORKFLOW_MAX_RETRIES
from ant_orchestrator.core.domain.value_objects import TaskId, WorkflowRunId
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.cancellation_probe import CancellationProbe
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    CHECKPOINT_DB_FILENAME,
    DATABASE_FILENAME,
)
from tests.support.scripted_worker import ScriptedStubAdapter


class _IntentRunner(WorkflowRunner):
    """A runner that injects structured action-intent flags into the initial state.

    The flags steer the decision node (significant-write / unsafe-command gates)
    exactly like a real worker plan would — no behaviour is inferred from text.
    """

    def __init__(
        self,
        *,
        significant_write: bool,
        unsafe_command: bool,
        energy_approval: bool,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._significant_write = significant_write
        self._unsafe_command = unsafe_command
        self._energy_approval = energy_approval

    def build_initial_state(
        self, *, task_id: str, workflow_run_id: str, base_retry_limit: int
    ) -> dict[str, object]:
        state = super().build_initial_state(
            task_id=task_id,
            workflow_run_id=workflow_run_id,
            base_retry_limit=base_retry_limit,
        )
        state["action_intent"] = {
            "requires_significant_write": self._significant_write,
            "requires_unsafe_command": self._unsafe_command,
            "requires_energy_approval": self._energy_approval,
        }
        return state


class _CrashRunWorkflow(RunWorkflow):
    """A RunWorkflow that invokes the graph but never runs a finalizer.

    Leaves a durable checkpoint (interrupted or END) with the WorkflowRun still
    RUNNING and no Approval / terminal transition — the exact crash window #2 / #7
    a fresh process must repair on the next ``run``.
    """

    def _invoke_and_finalize(
        self,
        run_id: WorkflowRunId,
        thread_id: str,
        task_id: TaskId,
        *,
        extras: dict[str, object] | None = None,
    ) -> WorkflowOutcome:
        initial_state = self._runner.build_initial_state(
            task_id=task_id.value,
            workflow_run_id=run_id.value,
            base_retry_limit=WORKFLOW_MAX_RETRIES,
        )
        if extras:
            initial_state.update(extras)
        self._runner.invoke(initial_state, thread_id=thread_id)
        return WorkflowOutcome(status="crashed", run_id=run_id.value)


@dataclass(frozen=True, slots=True)
class ScenarioServices:
    """The real Phase 4 services wired to one workspace with a scripted worker."""

    database: Database
    runner: WorkflowRunner
    create_task: CreateTask
    run_workflow: RunWorkflow
    crash_run_workflow: _CrashRunWorkflow
    resolve_approval: ResolveApproval
    cancel_task: CancelTask
    task_status: GetTaskStatus


def build_scenario_services(
    workspace: Path,
    *,
    outcomes: Sequence[WorkerOutcome],
    fallback: WorkerOutcome | None,
    base_retry_limit: int,
    significant_write: bool,
    unsafe_command: bool,
    energy_approval: bool = False,
    definition_version: int = WORKFLOW_DEFINITION_VERSION,
) -> ScenarioServices:
    """Assemble the real services against ``workspace`` with an injected worker."""
    ant_dir = workspace / ANT_DIRNAME
    database = Database(ant_dir / DATABASE_FILENAME)
    checkpoint_path = ant_dir / CHECKPOINT_DB_FILENAME

    clock = SystemClock()
    ids = Uuid4IdGenerator()

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(database)

    worker = ScriptedStubAdapter(outcomes, fallback=fallback)
    runner = _IntentRunner(
        significant_write=significant_write,
        unsafe_command=unsafe_command,
        energy_approval=energy_approval,
        worker=worker,
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=checkpoint_path,
        attempt_orchestrator=AttemptOrchestrator(uow_factory, clock=clock, ids=ids),
        cancellation_probe=CancellationProbe(uow_factory),
        definition_version=definition_version,
    )
    pause = PauseFinalizer(uow_factory, clock=clock, ids=ids)
    complete = CompletionFinalizer(uow_factory, clock=clock, ids=ids)

    return ScenarioServices(
        database=database,
        runner=runner,
        create_task=CreateTask(uow_factory, clock=clock, ids=ids),
        run_workflow=RunWorkflow(runner, uow_factory, pause, complete, clock=clock, ids=ids),
        crash_run_workflow=_CrashRunWorkflow(
            runner, uow_factory, pause, complete, clock=clock, ids=ids
        ),
        resolve_approval=ResolveApproval(
            runner, uow_factory, complete, pause, clock=clock, ids=ids
        ),
        cancel_task=CancelTask(runner, uow_factory, complete, clock=clock, ids=ids),
        task_status=GetTaskStatus(uow_factory),
    )


def seed_running_run(
    services: ScenarioServices,
    *,
    task_id: str,
    observed: bool,
    definition_version: int = WORKFLOW_DEFINITION_VERSION,
) -> str:
    """Insert a RUNNING run (no checkpoint) for crash#1 / lost-checkpoint scenarios.

    Returns the generated workflow run id. ``observed=True`` marks the run as
    having seen a checkpoint that is now absent (fail-closed lost-checkpoint case);
    ``observed=False`` is the never-invoked case (safe to re-START). A non-default
    ``definition_version`` seeds an incompatible run for the re-entry version guard.
    """
    from datetime import UTC, datetime

    from ant_orchestrator.application.services.workflow_support import (
        append_transition,
        thread_id_for,
    )
    from ant_orchestrator.core.domain.enums import (
        TaskStatus,
        TransitionSubject,
        TransitionTrigger,
        WorkflowRunStatus,
    )
    from ant_orchestrator.core.domain.value_objects import UtcTimestamp
    from ant_orchestrator.core.domain.workflow import WorkflowRun

    ids = Uuid4IdGenerator()
    run_id = WorkflowRunId(ids.new_id())
    now = UtcTimestamp(datetime.now(UTC))
    run = WorkflowRun(
        id=run_id,
        task_id=TaskId(task_id),
        thread_id=thread_id_for(run_id.value),
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=definition_version,
        initial_invoke_operation_id=f"seed-{run_id.value}",
        created_at=now,
        updated_at=now,
        checkpoint_ever_observed=observed,
        last_observed_checkpoint_id="ckpt-lost" if observed else None,
    )
    with SqliteUnitOfWork(services.database) as uow:
        task = uow.tasks.get(TaskId(task_id))
        uow.tasks.update(task.with_status(TaskStatus.RUNNING, now=now))
        uow.workflow_runs.add(run)
        append_transition(
            uow.transitions,
            ids=ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.RUN,
            to_status=WorkflowRunStatus.RUNNING.value,
            trigger=TransitionTrigger.RUN_CREATED,
            operation_id=f"seed-{run_id.value}",
        )
    return run_id.value


def seed_owned_resume(services: ScenarioServices, *, task_id: str, decision: str) -> str:
    """Insert an OWNED (in-flight, not completed) ResumeOperation for the pending gate.

    Simulates another process having acquired the resume lease with ``decision`` but
    not yet finalized, so a CLI command issuing a *different* decision hits a real
    ``ApprovalStateConflict`` (exit 5). Returns the resume-operation id.
    """
    from datetime import UTC, datetime

    from ant_orchestrator.core.domain.enums import ApprovalStatus, ResumeOperationStatus
    from ant_orchestrator.core.domain.value_objects import ResumeOperationId, UtcTimestamp
    from ant_orchestrator.core.domain.workflow import ResumeOperation

    now = UtcTimestamp(datetime.now(UTC))
    op_id = f"seed-resume-{decision}"
    with SqliteUnitOfWork(services.database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId(task_id))
        assert run is not None
        approval = uow.approvals.find_pending_by_run(run.id)
        assert approval is not None
        uow.resume_operations.add(
            ResumeOperation(
                id=ResumeOperationId(op_id),
                workflow_run_id=run.id,
                approval_id=approval.id,
                decision=ApprovalStatus(decision),
                status=ResumeOperationStatus.OWNED,
                created_at=now,
                langgraph_checkpoint_id=approval.langgraph_checkpoint_id,
                langgraph_interrupt_id=approval.langgraph_interrupt_id,
                owner_token="seed-other-owner",
            )
        )
    return op_id


def set_run_version(services: ScenarioServices, *, task_id: str, definition_version: int) -> str:
    """Force the active run's stored ``workflow_definition_version`` (re-entry guard).

    Simulates a run created by an older topology so a fresh process's re-entry guard
    fails closed before resuming. Returns the affected run id.
    """
    with SqliteUnitOfWork(services.database) as uow:
        run = uow.workflow_runs.find_active_by_task(TaskId(task_id))
        assert run is not None
        run_id = run.id.value
    with services.database.transaction() as conn:
        conn.execute(
            "UPDATE workflow_runs SET workflow_definition_version = ? WHERE id = ?",
            (definition_version, run_id),
        )
    return run_id
