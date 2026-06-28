"""Deterministic memory retrieval contract tests (Phase 7 CP2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    TaskPriority,
    TaskSource,
    TaskStatus,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from tests.conftest import FakeClock

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _ts(offset_seconds: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset_seconds))


def _mem(
    mem_id: str,
    *,
    memory_type: MemoryType = MemoryType.PROJECT_FACT,
    title: str = "t",
    summary: str = "s",
    ts: UtcTimestamp | None = None,
    source: str | None = None,
    confidence: ConfidenceLevel | None = None,
    tags: tuple[str, ...] = (),
    deprecated: bool = False,
    task_id: TaskId | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=memory_type,
        title=title,
        summary=summary,
        created_at=ts or _ts(),
        source=source,
        confidence=confidence,
        tags=tags,
        deprecated=deprecated,
        task_id=task_id,
    )


def _seed_task(db: Database, task_id: str = "TASK-1") -> TaskId:
    from ant_orchestrator.core.domain.entities import Task

    SqliteTaskRepository(db).add(
        Task(
            id=TaskId(task_id),
            title="task",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=_ts(),
            updated_at=_ts(),
        )
    )
    return TaskId(task_id)


# ---------------------------------------------------------------------------
# 7.1 Empty database
# ---------------------------------------------------------------------------


def test_empty_database_returns_empty(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    result = repo.search(MemorySearchCriteria(limit=10))
    assert len(result) == 0


# ---------------------------------------------------------------------------
# 7.2 Limit / no full-table dump
# ---------------------------------------------------------------------------


def test_limit_returns_exact_count(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    for i in range(10):
        repo.append(_mem(f"M-{i:02d}", ts=_ts(i)))
    result = repo.search(MemorySearchCriteria(limit=5))
    assert len(result) == 5


def test_limit_returns_newest_first_exact_ids(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    # Seed 8 records, timestamps 0..7 seconds
    for i in range(8):
        repo.append(_mem(f"M-{i:02d}", ts=_ts(i)))
    # limit=3 should return the 3 newest: M-07, M-06, M-05
    result = repo.search(MemorySearchCriteria(limit=3))
    assert [r.id.value for r in result] == ["M-07", "M-06", "M-05"]


# ---------------------------------------------------------------------------
# 7.3 Type filter
# ---------------------------------------------------------------------------


def test_type_filter_returns_only_matching_type(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-PF", memory_type=MemoryType.PROJECT_FACT))
    repo.append(_mem("M-TD", memory_type=MemoryType.TECHNICAL_DECISION))
    repo.append(_mem("M-KI", memory_type=MemoryType.KNOWN_ISSUE))

    result = repo.search(
        MemorySearchCriteria(memory_type=MemoryType.TECHNICAL_DECISION, limit=10)
    )
    assert len(result) == 1
    assert result[0].id.value == "M-TD"
    assert all(r.type is MemoryType.TECHNICAL_DECISION for r in result)


# ---------------------------------------------------------------------------
# 7.4 Task filter
# ---------------------------------------------------------------------------


def test_task_filter_returns_only_matching_task(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    tid_a = _seed_task(database, "TASK-A")
    tid_b = _seed_task(database, "TASK-B")

    repo.append(_mem("M-A", task_id=tid_a))
    repo.append(_mem("M-B", task_id=tid_b))
    repo.append(_mem("M-WS"))  # workspace-scoped (no task)

    result = repo.search(MemorySearchCriteria(task_id=tid_a, limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-A"


def test_task_filter_excludes_workspace_scoped(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    tid = _seed_task(database, "TASK-T")
    repo.append(_mem("M-T", task_id=tid))
    repo.append(_mem("M-WS"))

    result = repo.search(MemorySearchCriteria(task_id=tid, limit=10))
    ids = [r.id.value for r in result]
    assert "M-WS" not in ids


# ---------------------------------------------------------------------------
# 7.5 Source filter (case-sensitive)
# ---------------------------------------------------------------------------


def test_source_filter_exact_match(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-LO", source="user"))
    repo.append(_mem("M-HI", source="User"))
    repo.append(_mem("M-OT", source="system"))

    result = repo.search(MemorySearchCriteria(source="user", limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-LO"


def test_source_filter_case_sensitive(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-A", source="user"))
    repo.append(_mem("M-B", source="User"))

    lower = repo.search(MemorySearchCriteria(source="user", limit=10))
    upper = repo.search(MemorySearchCriteria(source="User", limit=10))
    assert {r.id.value for r in lower} == {"M-A"}
    assert {r.id.value for r in upper} == {"M-B"}


# ---------------------------------------------------------------------------
# 7.6 Confidence filter
# ---------------------------------------------------------------------------


def test_confidence_filter_returns_only_matching(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-L", confidence=ConfidenceLevel.LOW))
    repo.append(_mem("M-M", confidence=ConfidenceLevel.MEDIUM))
    repo.append(_mem("M-H", confidence=ConfidenceLevel.HIGH))

    result = repo.search(MemorySearchCriteria(confidence=ConfidenceLevel.HIGH, limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-H"


# ---------------------------------------------------------------------------
# 7.7 Tags ANY semantics
# ---------------------------------------------------------------------------


def test_tags_any_returns_records_with_at_least_one_tag(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-PY", tags=("python",)))
    repo.append(_mem("M-SQ", tags=("sqlite",)))
    repo.append(_mem("M-PS", tags=("python", "sqlite")))
    repo.append(_mem("M-NO", tags=("java",)))

    result = repo.search(MemorySearchCriteria(tags=("python", "sqlite"), limit=10))
    ids = {r.id.value for r in result}
    assert ids == {"M-PY", "M-SQ", "M-PS"}


def test_tags_any_does_not_require_all_tags(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-ONE", tags=("python",)))  # only one of two queried tags

    result = repo.search(MemorySearchCriteria(tags=("python", "sqlite"), limit=10))
    assert any(r.id.value == "M-ONE" for r in result)


# ---------------------------------------------------------------------------
# 7.8 Completeness: tag filter in SQL, not post-LIMIT Python
# ---------------------------------------------------------------------------


def test_completeness_beyond_candidate_window(database: Database) -> None:
    """Older matching record must be found even when many newer records exist without the tag."""
    repo = SqliteMemoryRepository(database)
    # Newest 10 records: no tag
    for i in range(10):
        repo.append(_mem(f"NEW-{i:02d}", ts=_ts(100 + i)))
    # Older record: has the matching tag
    repo.append(_mem("OLD-MATCH", tags=("rare-tag",), ts=_ts(0)))

    # Query with limit large enough to include the old record after SQL filtering
    result = repo.search(MemorySearchCriteria(tags=("rare-tag",), limit=20))
    ids = [r.id.value for r in result]
    assert "OLD-MATCH" in ids


def test_completeness_sql_filter_before_limit(database: Database) -> None:
    """SQL tag filter must apply before LIMIT, not after fetching N candidates."""
    repo = SqliteMemoryRepository(database)
    # 5 newest records: no match
    for i in range(5):
        repo.append(_mem(f"NOPE-{i}", ts=_ts(100 + i)))
    # 1 older matching record
    repo.append(_mem("HIT", tags=("target",), ts=_ts(0)))

    # limit=5 would miss HIT if filter were post-LIMIT Python
    # limit=6 ensures we get past the non-matching records
    result = repo.search(MemorySearchCriteria(tags=("target",), limit=6))
    assert any(r.id.value == "HIT" for r in result)

    # Crucially: with SQL filter, even limit=1 finds only HIT (no non-matching records pass)
    result_small = repo.search(MemorySearchCriteria(tags=("target",), limit=1))
    assert len(result_small) == 1
    assert result_small[0].id.value == "HIT"


# ---------------------------------------------------------------------------
# 7.9 Combined intersection
# ---------------------------------------------------------------------------


def test_combined_all_filters_intersection(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    tid = _seed_task(database, "TASK-C")

    # The "perfect match"
    repo.append(
        _mem(
            "M-MATCH",
            memory_type=MemoryType.KNOWN_ISSUE,
            source="ci",
            confidence=ConfidenceLevel.HIGH,
            tags=("bug",),
            task_id=tid,
        )
    )
    # Wrong type
    repo.append(
        _mem(
            "M-WRONG-TYPE",
            memory_type=MemoryType.PROJECT_FACT,
            source="ci",
            confidence=ConfidenceLevel.HIGH,
            tags=("bug",),
            task_id=tid,
        )
    )
    # Wrong source
    repo.append(
        _mem(
            "M-WRONG-SRC",
            memory_type=MemoryType.KNOWN_ISSUE,
            source="manual",
            confidence=ConfidenceLevel.HIGH,
            tags=("bug",),
            task_id=tid,
        )
    )
    # Wrong confidence
    repo.append(
        _mem(
            "M-WRONG-CONF",
            memory_type=MemoryType.KNOWN_ISSUE,
            source="ci",
            confidence=ConfidenceLevel.LOW,
            tags=("bug",),
            task_id=tid,
        )
    )
    # Wrong tag
    repo.append(
        _mem(
            "M-WRONG-TAG",
            memory_type=MemoryType.KNOWN_ISSUE,
            source="ci",
            confidence=ConfidenceLevel.HIGH,
            tags=("feature",),
            task_id=tid,
        )
    )
    # Wrong task
    repo.append(
        _mem(
            "M-WRONG-TASK",
            memory_type=MemoryType.KNOWN_ISSUE,
            source="ci",
            confidence=ConfidenceLevel.HIGH,
            tags=("bug",),
        )
    )

    result = repo.search(
        MemorySearchCriteria(
            memory_type=MemoryType.KNOWN_ISSUE,
            task_id=tid,
            source="ci",
            confidence=ConfidenceLevel.HIGH,
            tags=("bug",),
            limit=20,
        )
    )
    assert len(result) == 1
    assert result[0].id.value == "M-MATCH"


# ---------------------------------------------------------------------------
# 7.10 Deprecated behavior
# ---------------------------------------------------------------------------


def test_deprecated_excluded_by_default(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    active = _mem("M-ACT")
    depr = _mem("M-DEP")
    repo.append(active)
    repo.append(depr)
    repo.deprecate(depr)

    result = repo.search(MemorySearchCriteria(limit=10))
    ids = {r.id.value for r in result}
    assert "M-ACT" in ids
    assert "M-DEP" not in ids


def test_deprecated_included_when_flag_set(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    active = _mem("M-ACT")
    depr = _mem("M-DEP")
    repo.append(active)
    repo.append(depr)
    repo.deprecate(depr)

    result = repo.search(MemorySearchCriteria(include_deprecated=True, limit=10))
    ids = {r.id.value for r in result}
    assert "M-ACT" in ids
    assert "M-DEP" in ids


# ---------------------------------------------------------------------------
# 7.11 Stable newest-first ordering
# ---------------------------------------------------------------------------


def test_ordering_newest_first(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    # Insert in reverse order: oldest first, newest last
    for i in range(5):
        repo.append(_mem(f"M-{i}", ts=_ts(i * 10)))

    result = repo.search(MemorySearchCriteria(limit=5))
    ts_values = [r.created_at.value for r in result]
    # Each timestamp should be >= the next (newest first)
    for a, b in zip(ts_values, ts_values[1:]):
        assert a >= b


def test_ordering_exact_sequence(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-OLD", ts=_ts(0)))
    repo.append(_mem("M-MID", ts=_ts(100)))
    repo.append(_mem("M-NEW", ts=_ts(200)))

    result = repo.search(MemorySearchCriteria(limit=3))
    assert [r.id.value for r in result] == ["M-NEW", "M-MID", "M-OLD"]


# ---------------------------------------------------------------------------
# 7.12 Tie-breaker: same timestamp, ID ascending
# ---------------------------------------------------------------------------


def test_tiebreaker_id_ascending(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    same_ts = _ts(0)
    # Insert IDs out of alphabetical order
    for mem_id in ("M-Z", "M-A", "M-M", "M-B"):
        repo.append(_mem(mem_id, ts=same_ts))

    result = repo.search(MemorySearchCriteria(limit=10))
    assert [r.id.value for r in result] == ["M-A", "M-B", "M-M", "M-Z"]


# ---------------------------------------------------------------------------
# 7.13 Repeated query determinism
# ---------------------------------------------------------------------------


def test_repeated_query_same_order(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    for i in range(6):
        repo.append(_mem(f"M-{i:02d}", ts=_ts(i * 5)))

    criteria = MemorySearchCriteria(limit=4)
    first = [r.id.value for r in repo.search(criteria)]
    second = [r.id.value for r in repo.search(criteria)]
    third = [r.id.value for r in repo.search(criteria)]
    assert first == second == third


# ---------------------------------------------------------------------------
# 7.14 Invalid limit
# ---------------------------------------------------------------------------


def test_criteria_limit_zero_raises(database: Database) -> None:
    with pytest.raises(InvariantViolation):
        MemorySearchCriteria(limit=0)


def test_criteria_limit_negative_raises(database: Database) -> None:
    with pytest.raises(InvariantViolation):
        MemorySearchCriteria(limit=-1)


def test_criteria_limit_negative_large_raises(database: Database) -> None:
    with pytest.raises(InvariantViolation):
        MemorySearchCriteria(limit=-99)


# ---------------------------------------------------------------------------
# 7.15 SQL parameter safety
# ---------------------------------------------------------------------------


def test_sql_injection_in_source_is_safe(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    safe_source = "safe"
    attack_source = "' OR '1'='1"
    repo.append(_mem("M-SAFE", source=safe_source))
    repo.append(_mem("M-EVIL", source=attack_source))

    result = repo.search(MemorySearchCriteria(source=safe_source, limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-SAFE"


def test_sql_injection_in_tag_is_safe(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    repo.append(_mem("M-NORM", tags=("normal",)))
    repo.append(_mem("M-ATCK", tags=("' OR '1'='1",)))

    result = repo.search(MemorySearchCriteria(tags=("normal",), limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-NORM"


def test_sql_quote_in_source_exact_match(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    special = "it's a source"
    repo.append(_mem("M-SP", source=special))
    repo.append(_mem("M-PL", source="its a source"))

    result = repo.search(MemorySearchCriteria(source=special, limit=10))
    assert len(result) == 1
    assert result[0].id.value == "M-SP"


# ---------------------------------------------------------------------------
# 7.16 Cross-workspace retrieval isolation
# ---------------------------------------------------------------------------


def test_cross_workspace_search_isolation(tmp_path: Path, clock: FakeClock) -> None:
    db_a = tmp_path / "a.sqlite"
    db_b = tmp_path / "b.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_a)
    SqliteDatabaseBootstrapper(clock).bootstrap(db_b)

    repo_a = SqliteMemoryRepository(Database(db_a))
    repo_b = SqliteMemoryRepository(Database(db_b))

    repo_a.append(_mem("M-A", source="unique-source"))

    result_b = repo_b.search(MemorySearchCriteria(source="unique-source", limit=10))
    assert len(result_b) == 0


# ---------------------------------------------------------------------------
# 7.17 No-task-filter: returns workspace-scoped and task-scoped records
# ---------------------------------------------------------------------------


def test_no_task_filter_returns_both_scoped_and_workspace(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    tid = _seed_task(database, "TASK-WS")

    repo.append(_mem("M-TASK", task_id=tid))
    repo.append(_mem("M-WS"))  # workspace-scoped

    # No task_id in criteria means no filter on task_id column
    result = repo.search(MemorySearchCriteria(limit=10))
    ids = {r.id.value for r in result}
    assert "M-TASK" in ids
    assert "M-WS" in ids


def test_none_criteria_task_id_is_not_null_filter(database: Database) -> None:
    """Ensure criteria.task_id=None means 'no filter', not 'WHERE task_id IS NULL'."""
    repo = SqliteMemoryRepository(database)
    tid = _seed_task(database, "TASK-F")

    repo.append(_mem("M-HAS-TASK", task_id=tid))
    repo.append(_mem("M-NO-TASK"))  # task_id IS NULL

    result = repo.search(MemorySearchCriteria(task_id=None, limit=10))
    ids = {r.id.value for r in result}
    # Both must appear when task_id is not filtered
    assert "M-HAS-TASK" in ids
    assert "M-NO-TASK" in ids
