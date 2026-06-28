"""Domain query criteria for read-only retrieval operations (Phase 7 CP2)."""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TaskId


@dataclass(frozen=True, slots=True)
class MemorySearchCriteria:
    """Immutable, typed criteria for deterministic memory record retrieval.

    All filters combine with AND. ``tags`` uses ANY semantics (at least one tag
    must match). ``task_id=None`` means no task filter — both task-scoped and
    workspace-scoped records may be returned. ``limit`` must be positive; the
    application service layer is responsible for capping to ``MEMORY_MAX_LIMIT``.
    """

    memory_type: MemoryType | None = None
    task_id: TaskId | None = None
    source: str | None = None
    confidence: ConfidenceLevel | None = None
    tags: tuple[str, ...] = ()
    include_deprecated: bool = False
    limit: int = 1

    def __post_init__(self) -> None:
        if self.limit <= 0:
            raise InvariantViolation(
                f"MemorySearchCriteria.limit must be positive, got {self.limit}"
            )
