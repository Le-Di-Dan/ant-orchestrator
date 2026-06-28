"""Context-facing memory representation — application port layer (Phase 7 CP4).

Placed in application/ports so that ContextBuildRequest can reference
MemoryContextEntry without creating a reverse dependency from ports → context/.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ant_orchestrator.core.domain.records import MemoryRecord

_MEMORY_SOURCE_SEPARATOR = "\n---\n"


@dataclass(frozen=True, slots=True)
class MemoryContextEntry:
    """Immutable context-facing DTO. Single representation for worker context."""

    record_id: str
    type_value: str
    task_id_value: str | None
    source: str
    confidence_value: str
    title: str
    summary: str
    tags: tuple[str, ...]  # sorted alphabetically — stable across orderings

    def rendered_text(self) -> str:
        """Exact text fed to worker; budget + store + digest all based on this."""
        tag_line = ", ".join(self.tags) if self.tags else "none"
        return (
            f"[{self.type_value}] {self.title}\n"
            f"Source: {self.source} | Confidence: {self.confidence_value} | Tags: {tag_line}\n"
            f"{self.summary}"
        )

    def to_canonical(self) -> dict[str, object]:
        """Stable dict for digest (tags already sorted; caller JSON-sorts keys)."""
        return {
            "confidence": self.confidence_value,
            "id": self.record_id,
            "source": self.source,
            "summary": self.summary,
            "tags": list(self.tags),
            "task_id": self.task_id_value,
            "title": self.title,
            "type": self.type_value,
        }


@dataclass(frozen=True, slots=True)
class MemoryFilterManifest:
    """Structured evidence of the filter applied to retrieve these entries."""

    task_id: str | None
    memory_type: str | None
    source: str | None
    confidence: str | None
    tags: tuple[str, ...]  # sorted
    include_deprecated: bool
    resolved_limit: int


@dataclass(frozen=True, slots=True)
class MemoryContextSelection:
    """Memory selection result placed on ContextBuildRequest by CP5 preparer."""

    entries: tuple[MemoryContextEntry, ...]
    applied_filter: MemoryFilterManifest
    consumed_tokens: int


def combined_rendered_text(entries: tuple[MemoryContextEntry, ...]) -> str:
    """Exact combined worker text — source of truth for store and digest."""
    return _MEMORY_SOURCE_SEPARATOR.join(e.rendered_text() for e in entries)


def from_memory_record(record: MemoryRecord) -> MemoryContextEntry:
    """Convert a domain MemoryRecord to the context-facing DTO."""
    return MemoryContextEntry(
        record_id=record.id.value,
        type_value=record.type.value,
        task_id_value=record.task_id.value if record.task_id is not None else None,
        source=record.source or "",
        confidence_value=record.confidence.value if record.confidence is not None else "",
        title=record.title,
        summary=record.summary,
        tags=tuple(sorted(record.tags)),
    )
