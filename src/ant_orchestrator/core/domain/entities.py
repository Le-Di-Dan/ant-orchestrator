"""Domain entities with identity and a minimal lifecycle (PHASE_1_PLAN §7.1).

Entities are immutable; lifecycle changes return a new instance. Phase 1 does not
validate status transitions (D28) — only value invariants are enforced here.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ant_orchestrator.core.domain.enums import (
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import (
    TaskId,
    UtcTimestamp,
    WorkerRunId,
)


@dataclass(frozen=True, slots=True)
class Task:
    """A unit of work tracked by the orchestrator (WORKFLOW_SPEC §3/§15)."""

    id: TaskId
    title: str
    status: TaskStatus
    source: TaskSource
    priority: TaskPriority
    created_at: UtcTimestamp
    updated_at: UtcTimestamp

    def __post_init__(self) -> None:
        if not self.title:
            raise InvariantViolation("Task.title must be non-empty")
        if self.updated_at.value < self.created_at.value:
            raise InvariantViolation("Task.updated_at must not precede created_at")

    def with_status(self, status: TaskStatus, *, now: UtcTimestamp) -> Task:
        """Return a copy with a new status and refreshed ``updated_at``."""
        return replace(self, status=status, updated_at=now)


@dataclass(frozen=True, slots=True)
class WorkerRun:
    """A single execution of a worker against a Task (WORKFLOW_SPEC §9)."""

    id: WorkerRunId
    task_id: TaskId
    status: WorkerRunStatus
    created_at: UtcTimestamp
    started_at: UtcTimestamp | None = None
    finished_at: UtcTimestamp | None = None

    def with_status(
        self,
        status: WorkerRunStatus,
        *,
        started_at: UtcTimestamp | None = None,
        finished_at: UtcTimestamp | None = None,
    ) -> WorkerRun:
        """Return a copy with a new status and optional start/finish timestamps."""
        return replace(
            self,
            status=status,
            started_at=started_at if started_at is not None else self.started_at,
            finished_at=finished_at if finished_at is not None else self.finished_at,
        )
