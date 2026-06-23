"""Repository ports (Protocols) — the inner persistence boundary (PHASE_1_PLAN §7.3).

Operations are semantic (no generic CRUD/filter DSL). ``get`` raises
``persistence.RecordNotFound`` when absent; concrete adapters live in the
persistence layer. No delete operations in Phase 1.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ant_orchestrator.core.domain.entities import Task, WorkerRun
from ant_orchestrator.core.domain.enums import MemoryType
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
    HandoffId,
    MemoryId,
    PheromoneId,
    TaskId,
    WorkerRunId,
)


class TaskRepository(Protocol):
    """Persistence for Task entities (full lifecycle)."""

    def add(self, task: Task) -> None: ...
    def get(self, task_id: TaskId) -> Task: ...
    def update(self, task: Task) -> None: ...
    def list(self) -> Sequence[Task]: ...


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
    """Persistence for approvals with a resolve-once update."""

    def add(self, approval: Approval) -> None: ...
    def resolve(self, approval: Approval) -> None: ...
    def get(self, approval_id: ApprovalId) -> Approval: ...
    def list_by_task(self, task_id: TaskId) -> Sequence[Approval]: ...


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
