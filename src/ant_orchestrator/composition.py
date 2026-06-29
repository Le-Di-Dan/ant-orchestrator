"""Neutral composition root — assembles workflow services for all entry points.

Centralises all adapter/service wiring so that CLI commands, API routes, tests,
and future entry points can depend on a single assembly function. This module
must NOT import from ``cli/`` or ``api/`` — it is the shared neutral base.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.audit import AuditEvent, AuditSink
from ant_orchestrator.application.ports.audit_log_reader import (
    AuditLogPage,
    AuditLogQuery,
    AuditLogReader,
)
from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionPort,
    WorkflowDocumentationPreparer,
)
from ant_orchestrator.application.ports.worker import WorkerExecutionPort
from ant_orchestrator.application.ports.workspace import NestNotFound
from ant_orchestrator.application.services.cancel_task import CancelTask
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.create_task import CreateTask
from ant_orchestrator.application.services.get_task_detail import GetTaskDetail
from ant_orchestrator.application.services.get_task_logs import GetTaskLogs
from ant_orchestrator.application.services.get_task_result import GetTaskResult
from ant_orchestrator.application.services.get_worker_run_detail import GetWorkerRunDetail
from ant_orchestrator.application.services.get_workflow_run_detail import GetWorkflowRunDetail
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.application.services.reconciler import Reconciler
from ant_orchestrator.application.services.resolve_approval import ResolveApproval
from ant_orchestrator.application.services.run_workflow import RunWorkflow
from ant_orchestrator.application.services.search_memory import MemorySearchRequest, SearchMemory
from ant_orchestrator.application.services.task_status import GetTaskStatus
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.approval import SqliteApprovalRepository
from ant_orchestrator.persistence.repositories.energy_usage import SqliteEnergyUsageRepository
from ant_orchestrator.persistence.repositories.evidence import SqliteExecutionEvidenceRepository
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from ant_orchestrator.persistence.repositories.task_result import SqliteTaskResultRepository
from ant_orchestrator.persistence.repositories.worker_run import SqliteWorkerRunRepository
from ant_orchestrator.persistence.repositories.workflow_run import SqliteWorkflowRunReadRepository
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


class SystemClock:
    """Production Clock backed by the system UTC time."""

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(datetime.now(UTC))


class Uuid4IdGenerator:
    """Production IdGenerator backed by UUID4."""

    def new_id(self) -> str:
        return str(uuid.uuid4())


class _NullAuditSink:
    """Discards all audit events — used as default when no real sink is injected."""

    def write(self, event: AuditEvent) -> None:
        pass


class _NullAuditLogReader:
    """Returns empty page — used as default when no real reader is injected."""

    def read(self, query: AuditLogQuery) -> AuditLogPage:
        return AuditLogPage(events=(), corrupt_count=0, files_scanned=0, has_more=False)


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
    get_task_logs: GetTaskLogs
    get_task_detail: GetTaskDetail
    get_task_result: GetTaskResult
    get_worker_run_detail: GetWorkerRunDetail
    get_workflow_run_detail: GetWorkflowRunDetail


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
    worker: WorkerExecutionPort | None = None,
    documentation_execution: DocumentationExecutionPort | None = None,
    documentation_preparer: WorkflowDocumentationPreparer | None = None,
    audit_sink: AuditSink | None = None,
    audit_log_reader: AuditLogReader | None = None,
    clock: Clock | None = None,
    ids: IdGenerator | None = None,
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

    effective_clock: Clock = clock if clock is not None else SystemClock()
    effective_ids: IdGenerator = ids if ids is not None else Uuid4IdGenerator()

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(database)

    effective_sink: AuditSink = audit_sink if audit_sink is not None else _NullAuditSink()
    effective_reader: AuditLogReader = (
        audit_log_reader if audit_log_reader is not None else _NullAuditLogReader()
    )
    memory_repo = SqliteMemoryRepository(database)
    search_memory = SearchMemory(
        memory_repo, effective_sink, clock=effective_clock, ids=effective_ids
    )
    get_task_logs = GetTaskLogs(effective_reader)

    runner = WorkflowRunner(
        worker=worker if worker is not None else DeterministicStubAdapter(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=checkpoint_path,
        attempt_orchestrator=AttemptOrchestrator(
            uow_factory, clock=effective_clock, ids=effective_ids
        ),
        cancellation_probe=CancellationProbe(uow_factory),
        documentation_execution=documentation_execution,
    )
    pause = PauseFinalizer(uow_factory, clock=effective_clock, ids=effective_ids)
    complete = CompletionFinalizer(uow_factory, clock=effective_clock, ids=effective_ids)

    wf_read_repo = SqliteWorkflowRunReadRepository(database)
    get_task_detail = GetTaskDetail(
        task_repo=SqliteTaskRepository(database),
        workflow_run_repo=wf_read_repo,  # type: ignore[arg-type]
        worker_run_repo=SqliteWorkerRunRepository(database),
        energy_repo=SqliteEnergyUsageRepository(database),
        approval_repo=SqliteApprovalRepository(database),
    )
    get_worker_run_detail = GetWorkerRunDetail(
        worker_run_repo=SqliteWorkerRunRepository(database),
        energy_repo=SqliteEnergyUsageRepository(database),
        evidence_repo=SqliteExecutionEvidenceRepository(database),
    )
    get_workflow_run_detail = GetWorkflowRunDetail(workflow_run_repo=wf_read_repo)  # type: ignore[arg-type]

    return WorkflowServices(
        root=root,
        create_task=CreateTask(uow_factory, clock=effective_clock, ids=effective_ids),
        run_workflow=RunWorkflow(
            runner,
            uow_factory,
            pause,
            complete,
            clock=effective_clock,
            ids=effective_ids,
            documentation_preparer=documentation_preparer,
        ),
        resolve_approval=ResolveApproval(
            runner, uow_factory, complete, pause, clock=effective_clock, ids=effective_ids
        ),
        cancel_task=CancelTask(
            runner, uow_factory, complete, clock=effective_clock, ids=effective_ids
        ),
        reconciler=Reconciler(runner, uow_factory, pause, complete),
        task_status=GetTaskStatus(uow_factory),
        search_memory=search_memory,
        get_task_logs=get_task_logs,
        get_task_detail=get_task_detail,
        get_task_result=GetTaskResult(
            task_repo=SqliteTaskRepository(database),
            result_repo=SqliteTaskResultRepository(database),
        ),
        get_worker_run_detail=get_worker_run_detail,
        get_workflow_run_detail=get_workflow_run_detail,
    )
