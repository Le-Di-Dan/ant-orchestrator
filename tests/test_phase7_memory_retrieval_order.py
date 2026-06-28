"""Deterministic memory retrieval — ordering, validation, safety (Phase 7 CP2, §7.10-§7.17)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from tests.conftest import FakeClock
from tests.support.memory_retrieval_helpers import _mem, _seed_task, _ts

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
    for a, b in zip(ts_values, ts_values[1:], strict=False):
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
