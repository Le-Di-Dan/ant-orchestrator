"""Shared helpers for CP4 service integration tests (test-only).

Provides: InterruptRunner, factory functions, and task/run builders so each
individual test module stays within the 350-line file-size limit.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.reconciler import Reconciler
from ant_orchestrator.application.services.resolve_approval import ResolveApproval
from ant_orchestrator.application.services.run_workflow import RunWorkflow
from ant_orchestrator.application.services.workflow_support import (
    append_transition,
    thread_id_for,
)
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import (
    TaskPriority,
    TaskSource,
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    TaskId,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import WorkflowRun
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.workflow_runtime import CountingWorker


class InterruptRunner(WorkflowRunner):
    """Test double that causes the decision gate to always trigger REQUIRE_APPROVAL.

    Overrides ``build_initial_state`` to inject ``requires_significant_write=True``
    into the action_intent so the graph's decision node routes to prepare_intent.
    """

    def build_initial_state(
        self, *, task_id: str, workflow_run_id: str, base_retry_limit: int
    ) -> dict[str, object]:
        state = super().build_initial_state(
            task_id=task_id,
            workflow_run_id=workflow_run_id,
            base_retry_limit=base_retry_limit,
        )
        state["action_intent"] = {"requires_significant_write": True}
        return state


def make_interrupt_runner(tmp_path: Path, worker: CountingWorker) -> InterruptRunner:
    return InterruptRunner(
        worker=worker,
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
    )


def uow_factory(db: Database):
    return lambda: SqliteUnitOfWork(db)


def build_services(
    db: Database,
    runner: WorkflowRunner,
    clock: FakeClock,
    ids: SequentialIdGenerator,
):
    uow_f = uow_factory(db)
    pause = PauseFinalizer(uow_f, clock=clock, ids=ids)
    complete = CompletionFinalizer(uow_f, clock=clock, ids=ids)
    run_svc = RunWorkflow(runner, uow_f, pause, complete, clock=clock, ids=ids)
    resolve_svc = ResolveApproval(runner, uow_f, complete, pause, clock=clock, ids=ids)
    reconciler = Reconciler(runner, uow_f, pause, complete)
    return run_svc, resolve_svc, reconciler, pause, complete


def add_task(db: Database, task_id: str = "T1", *, clock: FakeClock) -> None:
    """Insert a CREATED task using the clock's timestamp to avoid invariant violations."""
    ts = clock.now()
    with SqliteUnitOfWork(db) as uow:
        uow.tasks.add(
            Task(
                id=TaskId(task_id),
                title="demo",
                status=TaskStatus.CREATED,
                source=TaskSource.HUMAN,
                priority=TaskPriority.NORMAL,
                created_at=ts,
                updated_at=ts,
            )
        )


def add_completed_task(db: Database, task_id: str, *, clock: FakeClock) -> None:
    ts = clock.now()
    with SqliteUnitOfWork(db) as uow:
        uow.tasks.add(
            Task(
                id=TaskId(task_id),
                title="demo",
                status=TaskStatus.COMPLETED,
                source=TaskSource.HUMAN,
                priority=TaskPriority.NORMAL,
                created_at=ts,
                updated_at=ts,
            )
        )


def create_running_run(
    database: Database,
    run_id: WorkflowRunId,
    task_id: str,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> WorkflowRun:
    """Insert a RUNNING WorkflowRun + its initial transition into the DB."""
    tid = thread_id_for(run_id.value)
    now = clock.now()
    run = WorkflowRun(
        id=run_id,
        task_id=TaskId(task_id),
        thread_id=tid,
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
        initial_invoke_operation_id=f"op-{run_id.value}",
        created_at=now,
        updated_at=now,
    )
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(run)
        append_transition(
            uow.transitions,
            ids=id_gen,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.RUN,
            to_status=WorkflowRunStatus.RUNNING.value,
            trigger=TransitionTrigger.RUN_CREATED,
            operation_id=f"op-{run_id.value}",
        )
    return run
