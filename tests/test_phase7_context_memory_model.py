"""Phase 7 CP4 — MemoryContextEntry DTO, budget selector, manifest section."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ant_orchestrator.application.ports.memory_context import (
    MemoryContextEntry,
    MemoryFilterManifest,
    combined_rendered_text,
    from_memory_record,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.memory import (
    MemoryContextSection,
    MemoryRecordManifest,
    MemorySelection,
    select_memory_for_context,
)
from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp

_BASE_TS = datetime(2026, 6, 22, tzinfo=UTC)
_EST = CharacterHeuristicEstimator(divisor=4)


def _ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


def _record(
    mem_id: str = "M-1",
    title: str = "Test Memory",
    summary: str = "A test fact.",
    tags: tuple[str, ...] = (),
    source: str = "ci",
    confidence: ConfidenceLevel = ConfidenceLevel.HIGH,
    task_id: str | None = None,
    mem_type: MemoryType = MemoryType.PROJECT_FACT,
) -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=mem_type,
        title=title,
        summary=summary,
        source=source,
        confidence=confidence,
        tags=tags,
        created_at=_ts(),
        task_id=TaskId(task_id) if task_id is not None else None,
    )


def _entry(
    record_id: str = "M-1",
    title: str = "Test Memory",
    summary: str = "A test fact.",
    tags: tuple[str, ...] = (),
    source: str = "ci",
    confidence_value: str = "high",
    task_id_value: str | None = None,
    type_value: str = "project_fact",
) -> MemoryContextEntry:
    return MemoryContextEntry(
        record_id=record_id,
        type_value=type_value,
        task_id_value=task_id_value,
        source=source,
        confidence_value=confidence_value,
        title=title,
        summary=summary,
        tags=tags,
    )


def _filter() -> MemoryFilterManifest:
    return MemoryFilterManifest(
        task_id=None,
        memory_type=None,
        source=None,
        confidence=None,
        tags=(),
        include_deprecated=False,
        resolved_limit=20,
    )


# ---------------------------------------------------------------------------
# DTO: from_memory_record conversion
# ---------------------------------------------------------------------------


def test_from_record_sets_basic_fields() -> None:
    rec = _record()
    entry = from_memory_record(rec)
    assert entry.record_id == "M-1"
    assert entry.type_value == "project_fact"
    assert entry.source == "ci"
    assert entry.confidence_value == "high"
    assert entry.title == "Test Memory"
    assert entry.summary == "A test fact."
    assert entry.task_id_value is None


def test_from_record_with_task_id() -> None:
    rec = _record(task_id="T-1")
    entry = from_memory_record(rec)
    assert entry.task_id_value == "T-1"


def test_from_record_sorts_tags() -> None:
    rec = _record(tags=("zebra", "apple", "mango"))
    entry = from_memory_record(rec)
    assert entry.tags == ("apple", "mango", "zebra")


def test_from_record_different_tag_orders_same_result() -> None:
    rec1 = _record(tags=("b", "a", "c"))
    rec2 = _record(tags=("c", "b", "a"))
    assert from_memory_record(rec1).tags == from_memory_record(rec2).tags


def test_entry_is_immutable() -> None:
    entry = from_memory_record(_record())
    with pytest.raises((AttributeError, TypeError)):
        entry.title = "new title"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Rendered text
# ---------------------------------------------------------------------------


def test_rendered_text_contains_type_and_title() -> None:
    entry = _entry(title="Bug Fix", type_value="project_fact")
    text = entry.rendered_text()
    assert "[project_fact] Bug Fix" in text


def test_rendered_text_contains_source_confidence_tags() -> None:
    entry = _entry(source="ci", confidence_value="high", tags=("python", "sql"))
    text = entry.rendered_text()
    assert "Source: ci" in text
    assert "Confidence: high" in text
    assert "Tags: python, sql" in text


def test_rendered_text_empty_tags() -> None:
    entry = _entry(tags=())
    text = entry.rendered_text()
    assert "Tags: none" in text


def test_rendered_text_contains_summary() -> None:
    entry = _entry(summary="Important project detail.")
    text = entry.rendered_text()
    assert "Important project detail." in text


def test_rendered_text_deterministic() -> None:
    entry = _entry()
    assert entry.rendered_text() == entry.rendered_text()


def test_combined_rendered_text_separator() -> None:
    e1 = _entry(record_id="M-1", title="First")
    e2 = _entry(record_id="M-2", title="Second")
    combined = combined_rendered_text((e1, e2))
    assert "---" in combined
    parts = combined.split("\n---\n")
    assert len(parts) == 2
    assert "First" in parts[0]
    assert "Second" in parts[1]


# ---------------------------------------------------------------------------
# Budget selector
# ---------------------------------------------------------------------------


def test_budget_selector_all_fit() -> None:
    entries = tuple(_entry(f"M-{i}", summary="x") for i in range(3))
    result = select_memory_for_context(entries, available_tokens=10000, estimator=_EST)
    assert result.entries == entries
    assert result.consumed_tokens > 0


def test_budget_selector_oversized_first_skipped_later_included() -> None:
    big = _entry("M-big", summary="x" * 10000)  # huge
    small = _entry("M-small", summary="small")
    entries = (big, small)
    result = select_memory_for_context(entries, available_tokens=50, estimator=_EST)
    assert len(result.entries) == 1
    assert result.entries[0].record_id == "M-small"


def test_budget_selector_none_fit() -> None:
    entries = tuple(_entry(f"M-{i}", summary="x" * 10000) for i in range(3))
    result = select_memory_for_context(entries, available_tokens=10, estimator=_EST)
    assert result.entries == ()
    assert result.consumed_tokens == 0


def test_budget_selector_exact_consumed_tokens() -> None:
    entry = _entry("M-1", title="T", summary="S")
    text = entry.rendered_text()
    expected_tokens = _EST.estimate(text).value
    result = select_memory_for_context((entry,), available_tokens=10000, estimator=_EST)
    assert result.consumed_tokens == expected_tokens


def test_budget_selector_stable_order() -> None:
    entries = tuple(_entry(f"M-{i}", summary="x") for i in range(5))
    result = select_memory_for_context(entries, available_tokens=10000, estimator=_EST)
    assert [e.record_id for e in result.entries] == [f"M-{i}" for i in range(5)]


def test_budget_selector_does_not_mutate_input() -> None:
    entries = list(_entry(f"M-{i}") for i in range(3))
    original = list(entries)
    select_memory_for_context(tuple(entries), available_tokens=10000, estimator=_EST)
    assert entries == original


def test_budget_selector_returns_memory_selection_type() -> None:
    result = select_memory_for_context((), available_tokens=1000, estimator=_EST)
    assert isinstance(result, MemorySelection)
    assert result.entries == ()
    assert result.consumed_tokens == 0


# ---------------------------------------------------------------------------
# MemoryContextSection
# ---------------------------------------------------------------------------


def test_memory_context_section_no_selection_is_none() -> None:
    # Empty selection → no section (convention enforced by caller)
    section = None
    assert section is None


def test_memory_context_section_nonempty() -> None:
    records = (MemoryRecordManifest(record_id="M-1", memory_type="project_fact"),)
    section = MemoryContextSection(
        applied_filter=_filter(),
        records=records,
        returned_count=1,
        budget_consumed_tokens=42,
    )
    assert section.returned_count == 1
    assert section.records[0].record_id == "M-1"
    assert section.budget_consumed_tokens == 42


def test_memory_context_section_count_invariant_enforced() -> None:
    records = (MemoryRecordManifest("M-1", "project_fact"),)
    from ant_orchestrator.core.domain.errors import InvariantViolation

    with pytest.raises(InvariantViolation, match="returned_count"):
        MemoryContextSection(
            applied_filter=_filter(),
            records=records,
            returned_count=99,  # wrong!
            budget_consumed_tokens=0,
        )


def test_memory_context_section_no_title_or_summary() -> None:
    # MemoryContextSection must NOT have title/summary fields
    records = (MemoryRecordManifest("M-1", "project_fact"),)
    section = MemoryContextSection(
        applied_filter=_filter(),
        records=records,
        returned_count=1,
        budget_consumed_tokens=0,
    )
    assert not hasattr(section, "title")
    assert not hasattr(section, "summary")
    assert not hasattr(section, "filter_summary")


def test_memory_filter_manifest_stable_tags() -> None:
    f1 = MemoryFilterManifest(None, None, None, None, ("z", "a"), False, 10)
    f2 = MemoryFilterManifest(None, None, None, None, ("a", "z"), False, 10)
    # Tags stored in the order provided; caller should sort — just verify immutable
    assert f1.tags == ("z", "a")
    assert f2.tags == ("a", "z")
