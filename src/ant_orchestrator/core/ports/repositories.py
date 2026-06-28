"""Repository ports (Protocols) — the inner persistence boundary (PHASE_1_PLAN §7.3).

Operations are semantic (no generic CRUD/filter DSL). ``get`` raises
``persistence.RecordNotFound`` when absent; concrete adapters live in the
persistence layer. No delete operations in Phase 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ant_orchestrator.core.domain.entities import Task, WorkerRun
from ant_orchestrator.core.domain.enums import MemoryType, TaskStatus, WorkflowRunStatus
from ant_orchestrator.core.domain.records import (
    Approval,
    EnergyUsage,
    ExecutionEvidence,
    HandoffRecord,
    MemoryRecord,
    PheromoneRecord,
    WorkflowCheckpoint,
)
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    CheckpointId,
    EnergyUsageId,
    EvidenceId,
    ExecutionAttemptId,
    GateInstanceId,
    HandoffId,
    MemoryId,
    PheromoneId,
    ResumeOperationId,
    TaskId,
    WorkerRunId,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import (
    ExecutionAttempt,
    ResumeOperation,
    StatusTransition,
    WorkflowRun,
)


class TaskRepository(Protocol):
    """Persistence for Task entities (full lifecycle)."""

    def add(self, task: Task) -> None: ...
    def get(self, task_id: TaskId) -> Task: ...
    def update(self, task: Task) -> None: ...
    def list(self) -> Sequence[Task]: ...
    def compare_and_set_status(self, task: Task, *, expected: TaskStatus) -> bool:
        """CAS the status; persist ``task`` only if the stored status == ``expected``.

        Returns ``True`` on success, ``False`` if another writer changed the status
        first (e.g. a terminal CANCELLED must not be overwritten by COMPLETED).
        """
        ...


class WorkerRunRepository(Protocol):
    """Persistence for WorkerRun entities."""

    def add(self, worker_run: WorkerRun) -> None: ...
    def get(self, worker_run_id: WorkerRunId) -> WorkerRun: ...
    def update(self, worker_run: WorkerRun) -> None: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[WorkerRun]: ...


class EnergyUsageRepository(Protocol):
    """Append-only persistence for EnergyUsage records."""

    def append(self, usage: EnergyUsage) -> None: ...
    def get(self, usage_id: EnergyUsageId) -> EnergyUsage: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[EnergyUsage]: ...
    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[EnergyUsage]: ...


class CheckpointRepository(Protocol):
    """Append-only persistence for workflow checkpoints."""

    def append(self, checkpoint: WorkflowCheckpoint) -> None: ...
    def get(self, checkpoint_id: CheckpointId) -> WorkflowCheckpoint: ...
    def get_latest_by_task(self, task_id: TaskId) -> WorkflowCheckpoint: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[WorkflowCheckpoint]: ...


class ApprovalRepository(Protocol):
    """Persistence for approvals with a resolve-once update.

    Phase 4 adds gate-instance lookup, pending-by-run lookup, and a row-version CAS
    resolve so a stale concurrent writer is rejected (PHASE_4_PLAN C.2/C.5).
    """

    def add(self, approval: Approval) -> None: ...
    def resolve(self, approval: Approval) -> None: ...
    def get(self, approval_id: ApprovalId) -> Approval: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[Approval]: ...
    def find_by_gate_instance(self, gate_instance_id: GateInstanceId) -> Approval | None: ...
    def find_pending_by_run(self, workflow_run_id: WorkflowRunId) -> Approval | None: ...
    def resolve_with_version(self, approval: Approval, *, expected_version: int) -> bool:
        """CAS resolve a pending approval iff ``approval_row_version == expected``.

        Returns ``True`` when the row was updated, ``False`` on a stale-version loss.
        """
        ...


class WorkflowRunRepository(Protocol):
    """Persistence for WorkflowRun execution identities (PHASE_4_PLAN E.1)."""

    def add(self, run: WorkflowRun) -> None: ...
    def get(self, run_id: WorkflowRunId) -> WorkflowRun: ...
    def update(self, run: WorkflowRun) -> None: ...
    def find_active_by_task(self, task_id: TaskId) -> WorkflowRun | None: ...
    def compare_and_set_status(self, run: WorkflowRun, *, expected: WorkflowRunStatus) -> bool:
        """CAS the run status; persist only if the stored status == ``expected``."""
        ...


class StatusTransitionRepository(Protocol):
    """Append-only persistence for lifecycle transitions (idempotent by operation_id)."""

    def append(self, transition: StatusTransition) -> None: ...
    def list_by_run(self, run_id: WorkflowRunId) -> Sequence[StatusTransition]: ...


class ExecutionAttemptRepository(Protocol):
    """Persistence for execution attempts (no exactly-once; PHASE_4_PLAN C.9)."""

    def add(self, attempt: ExecutionAttempt) -> None: ...
    def get(self, attempt_id: ExecutionAttemptId) -> ExecutionAttempt: ...
    def update(self, attempt: ExecutionAttempt) -> None: ...
    def find_active(self, run_id: WorkflowRunId, logical_action_id: str) -> ExecutionAttempt | None:
        """Return the single active (PLANNED/STARTED) attempt, if any."""
        ...

    def find_settled_succeeded(
        self, run_id: WorkflowRunId, logical_action_id: str
    ) -> ExecutionAttempt | None:
        """Return the most recent SUCCEEDED attempt for Window 3 recovery, or None."""
        ...

    def find_latest_settled_attempt(
        self, run_id: WorkflowRunId, logical_action_id: str
    ) -> ExecutionAttempt | None:
        """Return the most recent SUCCEEDED or FAILED attempt for recovery, or None."""
        ...

    def list_for_action(
        self, run_id: WorkflowRunId, logical_action_id: str
    ) -> Sequence[ExecutionAttempt]: ...


class ResumeOperationRepository(Protocol):
    """Persistence for concurrent-resume owner leases (PHASE_4_PLAN C.5b)."""

    def add(self, operation: ResumeOperation) -> None: ...
    def get(self, operation_id: ResumeOperationId) -> ResumeOperation: ...
    def update(self, operation: ResumeOperation) -> None: ...
    def find_by_approval(self, approval_id: ApprovalId) -> ResumeOperation | None: ...


class ExecutionEvidenceRepository(Protocol):
    """Append-only persistence for execution evidence."""

    def append(self, evidence: ExecutionEvidence) -> None: ...
    def get(self, evidence_id: EvidenceId) -> ExecutionEvidence: ...
    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[ExecutionEvidence]: ...


class HandoffRepository(Protocol):
    """Append-only persistence for handoff records."""

    def append(self, handoff: HandoffRecord) -> None: ...
    def get(self, handoff_id: HandoffId) -> HandoffRecord: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[HandoffRecord]: ...


class PheromoneRepository(Protocol):
    """Append-only persistence for pheromone records."""

    def append(self, pheromone: PheromoneRecord) -> None: ...
    def get(self, pheromone_id: PheromoneId) -> PheromoneRecord: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[PheromoneRecord]: ...


class MemoryRepository(Protocol):
    """Persistence for memory records (append/read/deprecate; no retrieval)."""

    def append(self, memory: MemoryRecord) -> None: ...
    def get(self, memory_id: MemoryId) -> MemoryRecord: ...
    def deprecate(self, memory: MemoryRecord) -> None: ...
    def list_by_type(self, memory_type: MemoryType) -> Sequence[MemoryRecord]: ...
