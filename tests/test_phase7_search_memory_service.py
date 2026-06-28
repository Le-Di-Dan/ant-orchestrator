"""Phase 7 CP3 — SearchMemory service tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ant_orchestrator.application.ports.audit import AuditEvent, AuditEventType
from ant_orchestrator.application.services.search_memory import MemorySearchRequest, SearchMemory
from ant_orchestrator.config.constants import MEMORY_DEFAULT_LIMIT, MEMORY_MAX_LIMIT
from ant_orchestrator.core.domain.enums import ConfidenceLevel, MemoryType
from ant_orchestrator.core.domain.errors import DomainError
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, UtcTimestamp
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.fake_query_repos import FakeMemoryRepository

_BASE_TS = datetime(2026, 6, 22, tzinfo=UTC)


def _ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


def _mem_record(mem_id: str = "M-1") -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=MemoryType.PROJECT_FACT,
        title="title",
        summary="summary",
        created_at=_ts(),
    )


class FailAuditSink:
    def write(self, event: AuditEvent) -> None:
        raise RuntimeError("audit sink failed")


def _make_search_memory(
    records: list[MemoryRecord] | None = None,
    fail_audit: bool = False,
) -> tuple[SearchMemory, FakeMemoryRepository, FakeAuditSink]:
    repo = FakeMemoryRepository(records)
    sink: FakeAuditSink | FailAuditSink = FakeAuditSink() if not fail_audit else FailAuditSink()
    clock = FakeClock(UtcTimestamp(_BASE_TS))
    ids = SequentialIdGenerator()
    svc = SearchMemory(repo, sink, clock=clock, ids=ids)
    return svc, repo, sink  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Limit resolution
# ---------------------------------------------------------------------------


def test_omitted_limit_resolves_to_default() -> None:
    svc, repo, _ = _make_search_memory()
    svc.execute(MemorySearchRequest())
    assert repo.last_criteria is not None
    assert repo.last_criteria.limit == MEMORY_DEFAULT_LIMIT


def test_explicit_positive_limit_preserved() -> None:
    svc, repo, _ = _make_search_memory()
    svc.execute(MemorySearchRequest(limit=7))
    assert repo.last_criteria is not None
    assert repo.last_criteria.limit == 7


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_limit_zero_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="positive"):
        svc.execute(MemorySearchRequest(limit=0))


def test_limit_negative_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="positive"):
        svc.execute(MemorySearchRequest(limit=-1))


def test_limit_over_max_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="exceeds maximum"):
        svc.execute(MemorySearchRequest(limit=MEMORY_MAX_LIMIT + 1))


def test_invalid_memory_type_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="memory_type"):
        svc.execute(MemorySearchRequest(memory_type="not_a_type"))


def test_invalid_confidence_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="confidence"):
        svc.execute(MemorySearchRequest(confidence="very_high"))


def test_empty_tag_raises_domain_error() -> None:
    svc, _, _ = _make_search_memory()
    with pytest.raises(DomainError, match="empty"):
        svc.execute(MemorySearchRequest(tags=("valid", "")))


def test_repo_not_called_when_validation_fails() -> None:
    svc, repo, _ = _make_search_memory()
    with pytest.raises(DomainError):
        svc.execute(MemorySearchRequest(limit=0))
    assert repo.last_criteria is None


# ---------------------------------------------------------------------------
# Typed criteria conversion
# ---------------------------------------------------------------------------


def test_typed_criteria_sent_to_repository() -> None:
    svc, repo, _ = _make_search_memory()
    svc.execute(
        MemorySearchRequest(
            memory_type=MemoryType.PROJECT_FACT.value,
            source="ci",
            confidence=ConfidenceLevel.HIGH.value,
            tags=("bug", "sql"),
            include_deprecated=True,
            limit=5,
        )
    )
    c = repo.last_criteria
    assert c is not None
    assert c.memory_type is MemoryType.PROJECT_FACT
    assert c.source == "ci"
    assert c.confidence is ConfidenceLevel.HIGH
    assert c.tags == ("bug", "sql")
    assert c.include_deprecated is True
    assert c.limit == 5


def test_none_task_id_not_passed_to_criteria() -> None:
    svc, repo, _ = _make_search_memory()
    svc.execute(MemorySearchRequest(task_id=None))
    assert repo.last_criteria is not None
    assert repo.last_criteria.task_id is None


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------


def test_empty_repository_result_returns_empty_tuple() -> None:
    svc, _, _ = _make_search_memory(records=[])
    result = svc.execute(MemorySearchRequest())
    assert result.records == ()
    assert result.returned_count == 0


def test_records_preserved_in_order() -> None:
    recs = [_mem_record(f"M-{i}") for i in range(3)]
    svc, _, _ = _make_search_memory(records=recs)
    result = svc.execute(MemorySearchRequest())
    assert len(result.records) == 3
    assert result.records[0].id.value == "M-0"
    assert result.records[2].id.value == "M-2"


def test_result_contains_criteria() -> None:
    svc, _, _ = _make_search_memory()
    result = svc.execute(MemorySearchRequest(limit=7))
    assert result.criteria.limit == 7
    assert result.resolved_limit == 7


# ---------------------------------------------------------------------------
# Audit event
# ---------------------------------------------------------------------------


def test_audit_event_emitted() -> None:
    svc, _, sink = _make_search_memory()
    svc.execute(MemorySearchRequest())
    assert len(sink.events) == 1
    assert sink.events[0].event_type is AuditEventType.MEMORY_RETRIEVAL


def test_audit_event_no_title_summary_content() -> None:
    recs = [_mem_record("M-1")]
    svc, _, sink = _make_search_memory(records=recs)
    svc.execute(MemorySearchRequest())
    detail = sink.events[0].detail
    assert "title" not in detail
    assert "summary" not in detail


def test_audit_detail_has_aggregate_metadata() -> None:
    svc, _, sink = _make_search_memory(records=[_mem_record()])
    svc.execute(MemorySearchRequest(limit=7, tags=("a", "b")))
    detail = sink.events[0].detail
    assert detail["tags_count"] == "2"
    assert detail["resolved_limit"] == "7"
    assert detail["returned_count"] == "1"


def test_audit_failure_propagates() -> None:
    svc, _, _ = _make_search_memory(fail_audit=True)
    with pytest.raises(RuntimeError, match="audit sink failed"):
        svc.execute(MemorySearchRequest())
