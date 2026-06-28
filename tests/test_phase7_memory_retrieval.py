"""Deterministic memory retrieval — basic filters (Phase 7 CP2, sections 7.1-7.9)."""

from __future__ import annotations

from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from tests.support.memory_retrieval_helpers import _mem, _seed_task, _ts

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

    result = repo.search(MemorySearchCriteria(memory_type=MemoryType.TECHNICAL_DECISION, limit=10))
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
