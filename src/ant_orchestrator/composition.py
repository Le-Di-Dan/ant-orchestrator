"""Neutral composition root — assembles workflow services for all entry points.

Centralises all adapter/service wiring so that CLI commands, tests, and future
entry points can depend on a single assembly function. Phase 7 CP5 adds
``SearchMemory`` and the helper ``make_memory_retriever`` that adapts it to the
``_MemoryRetriever`` port expected by ``ContextSourcePreparerImpl``.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.application.ports.audit import AuditEvent, AuditSink
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
from ant_orchestrator.application.services.search_memory import MemorySearchRequest, SearchMemory
from ant_orchestrator.application.services.task_status import GetTaskStatus
from ant_orchestrator.cli.composition import SystemClock, Uuid4IdGenerator
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
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


class _NullAuditSink:
    """Discards all audit events — used as default when no real sink is injected."""

    def write(self, event: AuditEvent) -> None:
        pass


@dataclass(frozen=True, slots=True)
class WorkflowServices:
    """Workflow use cases + supporting services bound to one discovered Nest."""

    root: Path
    create_task: CreateTask
    run_workflow: RunWorkflow
    resolve_approval: ResolveApproval
    cancel_task: CancelTask
    reconciler: Reconciler
    task_status: GetTaskStatus
    search_memory: SearchMemory


def make_memory_retriever(
    search: SearchMemory,
) -> Callable[[MemorySearchCriteria], Sequence[MemoryRecord]]:
    """Return a callable adapting ``SearchMemory`` to the ``_MemoryRetriever`` port."""

    def _retrieve(criteria: MemorySearchCriteria) -> Sequence[MemoryRecord]:
        req = MemorySearchRequest(
            task_id=criteria.task_id.value if criteria.task_id else None,
            memory_type=criteria.memory_type.value if criteria.memory_type else None,
            source=criteria.source,
            confidence=criteria.confidence.value if criteria.confidence else None,
            tags=criteria.tags,
            include_deprecated=criteria.include_deprecated,
            limit=criteria.limit,
        )
        return search.execute(req).records

    return _retrieve


def build_workflow_services(
    start: Path,
    *,
    documentation_execution: DocumentationExecutionPort | None = None,
    documentation_preparer: WorkflowDocumentationPreparer | None = None,
    audit_sink: AuditSink | None = None,
) -> WorkflowServices:
    """Discover the Nest from ``start`` and assemble all workflow services.

    Raises :class:`NestNotFound` (→ exit 3) when no ``.ant/`` exists at or above
    ``start``; storage/schema problems surface later as ``DatabasePortError`` (→ 4).
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

    effective_sink: AuditSink = audit_sink if audit_sink is not None else _NullAuditSink()
    memory_repo = SqliteMemoryRepository(database)
    search_memory = SearchMemory(memory_repo, effective_sink, clock=clock, ids=ids)

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
        search_memory=search_memory,
    )
