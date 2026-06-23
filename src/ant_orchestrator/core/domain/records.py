"""Append-only domain records and the Approval entity (PHASE_1_PLAN §7.1/§7.3).

All records are immutable. ``Approval.resolve`` and ``MemoryRecord.deprecate``
return new instances rather than mutating in place (D31/D07).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ConfidenceLevel,
    MemoryType,
    PheromoneType,
)
from ant_orchestrator.core.domain.errors import (
    ApprovalAlreadyResolved,
    InvariantViolation,
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
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)


@dataclass(frozen=True, slots=True)
class EnergyUsage:
    """Recorded token usage; tied to a task and/or a worker run."""

    id: EnergyUsageId
    tokens_in: TokenCount
    tokens_out: TokenCount
    created_at: UtcTimestamp
    task_id: TaskId | None = None
    worker_run_id: WorkerRunId | None = None

    def __post_init__(self) -> None:
        if self.task_id is None and self.worker_run_id is None:
            raise InvariantViolation("EnergyUsage requires task_id or worker_run_id")


@dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    """An opaque, JSON-serializable snapshot of workflow state (D33)."""

    id: CheckpointId
    task_id: TaskId
    payload_version: int
    payload: Mapping[str, object]
    created_at: UtcTimestamp

    def __post_init__(self) -> None:
        if self.payload_version < 1:
            raise InvariantViolation("WorkflowCheckpoint.payload_version must be >= 1")


@dataclass(frozen=True, slots=True)
class Approval:
    """A human-approval decision with a resolve-once lifecycle (D31)."""

    id: ApprovalId
    task_id: TaskId
    status: ApprovalStatus
    requested_at: UtcTimestamp
    checkpoint_id: CheckpointId | None = None
    reason: str | None = None
    decided_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        pending = self.status is ApprovalStatus.PENDING
        if pending and self.decided_at is not None:
            raise InvariantViolation("Pending approval must not have decided_at")
        if not pending and self.decided_at is None:
            raise InvariantViolation("Resolved approval requires decided_at")

    def resolve(
        self,
        decision: ApprovalStatus,
        *,
        decided_at: UtcTimestamp,
        reason: str | None = None,
    ) -> Approval:
        """Return a resolved copy. Raises if already resolved or decision invalid."""
        if self.status is not ApprovalStatus.PENDING:
            raise ApprovalAlreadyResolved(f"Approval {self.id} already {self.status}")
        if decision not in (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED):
            raise InvariantViolation(f"Cannot resolve with status {decision}")
        return replace(
            self,
            status=decision,
            decided_at=decided_at,
            reason=reason if reason is not None else self.reason,
        )


@dataclass(frozen=True, slots=True)
class ExecutionEvidence:
    """Audit trail of a worker run's reads/changes/commands (WORKFLOW_SPEC §9)."""

    id: EvidenceId
    worker_run_id: WorkerRunId
    created_at: UtcTimestamp
    files_read: tuple[str, ...] = ()
    files_changed: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    result: str | None = None


@dataclass(frozen=True, slots=True)
class HandoffRecord:
    """A short post-task handoff summary (WORKFLOW_SPEC §14)."""

    id: HandoffId
    task_id: TaskId
    summary: str
    created_at: UtcTimestamp
    what_changed: str | None = None
    next_steps: str | None = None

    def __post_init__(self) -> None:
        if not self.summary:
            raise InvariantViolation("HandoffRecord.summary must be non-empty")


@dataclass(frozen=True, slots=True)
class PheromoneRecord:
    """A short-term coordination trace (MEMORY_AND_PHEROMONE_SPEC §6/§7)."""

    id: PheromoneId
    type: PheromoneType
    summary: str
    created_at: UtcTimestamp
    task_id: TaskId | None = None
    files: tuple[str, ...] = ()
    expires_at: UtcTimestamp | None = None
    confidence: ConfidenceLevel | None = None

    def __post_init__(self) -> None:
        if not self.summary:
            raise InvariantViolation("PheromoneRecord.summary must be non-empty")


@dataclass(frozen=True, slots=True)
class MemoryRecord:
    """A long-term colony memory record (MEMORY_AND_PHEROMONE_SPEC §4/§5)."""

    id: MemoryId
    type: MemoryType
    title: str
    summary: str
    created_at: UtcTimestamp
    source: str | None = None
    confidence: ConfidenceLevel | None = None
    tags: tuple[str, ...] = field(default_factory=tuple)
    deprecated: bool = False

    def __post_init__(self) -> None:
        if not self.title:
            raise InvariantViolation("MemoryRecord.title must be non-empty")
        if not self.summary:
            raise InvariantViolation("MemoryRecord.summary must be non-empty")

    def deprecate(self) -> MemoryRecord:
        """Return a copy marked as deprecated (D07)."""
        return replace(self, deprecated=True)
