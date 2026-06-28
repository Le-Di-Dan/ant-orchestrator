"""Context-memory manifest evidence and pure budget selector (Phase 7 CP4)."""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.memory_context import (
    MemoryContextEntry,
    MemoryFilterManifest,
)
from ant_orchestrator.context.estimator import TokenEstimator
from ant_orchestrator.core.domain.errors import InvariantViolation

_MEMORY_LOGICAL_PATH = "memory://ant/context"
_MEMORY_PHYSICAL_FILE = "sources/memory_context.txt"


@dataclass(frozen=True, slots=True)
class MemoryRecordManifest:
    """Compact record reference in structured manifest evidence."""

    record_id: str
    memory_type: str


@dataclass(frozen=True, slots=True)
class MemoryContextSection:
    """Structured manifest section — no free-form strings, no raw content."""

    applied_filter: MemoryFilterManifest
    records: tuple[MemoryRecordManifest, ...]
    returned_count: int
    budget_consumed_tokens: int

    def __post_init__(self) -> None:
        if self.returned_count != len(self.records):
            raise InvariantViolation("MemoryContextSection.returned_count must equal len(records)")
        if self.budget_consumed_tokens < 0:
            raise InvariantViolation("MemoryContextSection.budget_consumed_tokens must be >= 0")


@dataclass(frozen=True, slots=True)
class MemorySelection:
    """Pure output of the memory budget selector."""

    entries: tuple[MemoryContextEntry, ...]
    consumed_tokens: int


def select_memory_for_context(
    candidates: tuple[MemoryContextEntry, ...],
    available_tokens: int,
    estimator: TokenEstimator,
) -> MemorySelection:
    """Pure budget-bounded selection.

    Semantics:
    - Preserve candidate order.
    - Estimate each entry via entry.rendered_text().
    - Include if fits within remaining budget; skip if not (do NOT stop).
    - Never truncate an entry's text.
    - Never exceed available_tokens.
    """
    included: list[MemoryContextEntry] = []
    consumed = 0
    for entry in candidates:
        tokens = estimator.estimate(entry.rendered_text()).value
        if consumed + tokens <= available_tokens:
            included.append(entry)
            consumed += tokens
    return MemorySelection(entries=tuple(included), consumed_tokens=consumed)
