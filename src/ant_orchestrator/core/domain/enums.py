"""Domain enumerations and their authoritative value sets (PHASE_1_PLAN §7.2).

Every member's ``value`` is the canonical string persisted in SQLite (stored as
TEXT with a CHECK constraint). Phase 1 validates *membership* only; status
transitions are not validated until the workflow phase (Phase 4).
"""

from __future__ import annotations

from enum import Enum
from typing import Self

from ant_orchestrator.core.domain.errors import InvalidStatusValue


class _StrEnum(Enum):
    """Base enum whose value is a string, with safe membership parsing."""

    @classmethod
    def parse(cls, raw: str) -> Self:
        """Return the member matching ``raw`` or raise ``InvalidStatusValue``."""
        try:
            return cls(raw)
        except ValueError as exc:
            raise InvalidStatusValue(f"{cls.__name__}: unknown value {raw!r}") from exc

    def __str__(self) -> str:
        value = self.value
        assert isinstance(value, str)
        return value


class TaskStatus(_StrEnum):
    """Lifecycle of a Task (WORKFLOW_SPEC §15 + ROADMAP §8/§9)."""

    CREATED = "created"
    CLASSIFIED = "classified"
    PLANNED = "planned"
    SPLIT = "split"
    ASSIGNED = "assigned"
    RUNNING = "running"
    VALIDATING = "validating"
    REVIEWING = "reviewing"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        """True for terminal task outcomes (ROADMAP §9)."""
        return self in _TERMINAL_TASK_STATUSES


class ApprovalStatus(_StrEnum):
    """State of a human-approval decision (ROADMAP §8/§9)."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

    @property
    def is_terminal(self) -> bool:
        """True once the approval has been decided."""
        return self in _TERMINAL_APPROVAL_STATUSES


class WorkerRunStatus(_StrEnum):
    """Lifecycle of a WorkerRun (assumption, GĐ-5)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        """True for terminal worker-run outcomes."""
        return self in _TERMINAL_WORKER_RUN_STATUSES


class TaskSource(_StrEnum):
    """Origin of a Task (WORKFLOW_SPEC §3 intake)."""

    HUMAN = "human"
    CLI = "cli"
    API = "api"


class TaskPriority(_StrEnum):
    """Task priority. ``normal`` from WORKFLOW_SPEC §3; low/high assumption (GĐ-9)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class ConfidenceLevel(_StrEnum):
    """Qualitative confidence. high/medium from MEMORY spec; low assumption (GĐ-9)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class PheromoneType(_StrEnum):
    """Short-term pheromone categories (MEMORY_AND_PHEROMONE_SPEC §6)."""

    FILE_RELEVANCE = "file_relevance"
    TEST_FAILURE = "test_failure"
    WORKER_NOTE = "worker_note"
    RISK_SIGNAL = "risk_signal"
    NEXT_STEP = "next_step"
    BLOCKED_REASON = "blocked_reason"
    CONTEXT_HINT = "context_hint"


class MemoryType(_StrEnum):
    """Long-term memory categories (MEMORY_AND_PHEROMONE_SPEC §4)."""

    PROJECT_FACT = "project_fact"
    TECHNICAL_DECISION = "technical_decision"
    CODING_CONVENTION = "coding_convention"
    ARCHITECTURE_SUMMARY = "architecture_summary"
    KNOWN_ISSUE = "known_issue"
    SUCCESSFUL_PATTERN = "successful_pattern"
    HUMAN_PREFERENCE = "human_preference"
    RISK_NOTE = "risk_note"


_TERMINAL_TASK_STATUSES = frozenset(
    {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.REJECTED}
)
_TERMINAL_APPROVAL_STATUSES = frozenset({ApprovalStatus.APPROVED, ApprovalStatus.REJECTED})
_TERMINAL_WORKER_RUN_STATUSES = frozenset(
    {WorkerRunStatus.SUCCEEDED, WorkerRunStatus.FAILED, WorkerRunStatus.CANCELLED}
)
