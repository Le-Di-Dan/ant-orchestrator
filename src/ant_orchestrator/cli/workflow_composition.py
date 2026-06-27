"""Composition root for the Phase 4 workflow CLI commands (PHASE_4_PLAN CP7 §13).

Discovers the ``.ant/`` Nest, opens the (separate) state and checkpoint databases and
wires the deterministic stub worker, graph runner, finalizers, reconciler and the
task/run/approval/cancel use cases. No SQLite connection is held globally: the
``Database`` hands out short-lived connections and the runner opens its checkpointer
per call, so every resource is released when a command returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionPort,
    WorkflowDocumentationPreparer,
)
from ant_orchestrator.application.ports.workspace import NestNotFound
from ant_orchestrator.application.services.cancel_task import CancelTask
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.create_task import CreateTask
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.reconciler import Reconciler
from ant_orchestrator.application.services.resolve_approval import ResolveApproval
from ant_orchestrator.application.services.run_workflow import RunWorkflow
from ant_orchestrator.application.services.task_status import GetTaskStatus
from ant_orchestrator.cli.composition import SystemClock, Uuid4IdGenerator
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workers.stub import DeterministicStubAdapter
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.cancellation_probe import CancellationProbe
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workspace.discovery import find_nest
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    CHECKPOINT_DB_FILENAME,
    DATABASE_FILENAME,
)


@dataclass(frozen=True, slots=True)
class WorkflowServices:
    """The Phase 4 use cases bound to one discovered Nest."""

    root: Path
    create_task: CreateTask
    run_workflow: RunWorkflow
    resolve_approval: ResolveApproval
    cancel_task: CancelTask
    reconciler: Reconciler
    task_status: GetTaskStatus


def build_workflow_services(
    start: Path,
    *,
    documentation_execution: DocumentationExecutionPort | None = None,
    documentation_preparer: WorkflowDocumentationPreparer | None = None,
) -> WorkflowServices:
    """Discover the Nest from ``start`` and assemble the Phase 4/5 services.

    Raises :class:`NestNotFound` (→ exit 3) when no ``.ant/`` exists at or above
    ``start``; storage/schema problems surface later as ``DatabasePortError`` (→ 4).

    Phase 5 CP6: injecting ``documentation_execution`` + ``documentation_preparer`` switches
    the production path to the durable Documentation Ant (proposal/approval bound, durable
    persistence). When omitted (Phase 4 / legacy), the deterministic stub worker is used —
    the live provider wiring of these two collaborators is assembled in CP7.
    """
    root = find_nest(start)
    if root is None:
        raise NestNotFound(f"No .ant/ found from {start}")

    ant_dir = root / ANT_DIRNAME
    database = Database(ant_dir / DATABASE_FILENAME)
    checkpoint_path = ant_dir / CHECKPOINT_DB_FILENAME

    clock = SystemClock()
    ids = Uuid4IdGenerator()

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(database)

    runner = WorkflowRunner(
        worker=DeterministicStubAdapter(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=checkpoint_path,
        attempt_orchestrator=AttemptOrchestrator(uow_factory, clock=clock, ids=ids),
        cancellation_probe=CancellationProbe(uow_factory),
        documentation_execution=documentation_execution,
    )
    pause = PauseFinalizer(uow_factory, clock=clock, ids=ids)
    complete = CompletionFinalizer(uow_factory, clock=clock, ids=ids)

    return WorkflowServices(
        root=root,
        create_task=CreateTask(uow_factory, clock=clock, ids=ids),
        run_workflow=RunWorkflow(
            runner,
            uow_factory,
            pause,
            complete,
            clock=clock,
            ids=ids,
            documentation_preparer=documentation_preparer,
        ),
        resolve_approval=ResolveApproval(
            runner, uow_factory, complete, pause, clock=clock, ids=ids
        ),
        cancel_task=CancelTask(runner, uow_factory, complete, clock=clock, ids=ids),
        reconciler=Reconciler(runner, uow_factory, pause, complete),
        task_status=GetTaskStatus(uow_factory),
    )
