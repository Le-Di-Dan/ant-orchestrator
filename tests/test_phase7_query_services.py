"""Phase 7 CP3 query-service tests: SearchMemory, GetTaskLogs, GetTaskDetail, GetWorkerRunDetail."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ant_orchestrator.application.models.execution_views import (
    EnergyTotalsView,
    TaskDetailView,
    WorkerRunDetailView,
)
from ant_orchestrator.application.ports.audit import AuditEvent, AuditEventType
from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage, AuditLogQuery
from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.application.services.get_task_detail import GetTaskDetail
from ant_orchestrator.application.services.get_task_logs import GetTaskLogs
from ant_orchestrator.application.services.get_worker_run_detail import GetWorkerRunDetail
from ant_orchestrator.application.services.search_memory import MemorySearchRequest, SearchMemory
from ant_orchestrator.config.constants import MEMORY_DEFAULT_LIMIT, MEMORY_MAX_LIMIT
from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.errors import DomainError
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence, MemoryRecord
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    MemoryId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_BASE_TS = datetime(2026, 6, 22, tzinfo=UTC)


def _ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMemoryRepository:
    """In-memory MemoryRepository fake for unit tests."""

    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records: list[MemoryRecord] = list(records or [])
        self.last_criteria: MemorySearchCriteria | None = None

    def append(self, memory: MemoryRecord) -> None:
        self._records.append(memory)

    def get(self, memory_id: MemoryId) -> MemoryRecord:
        for r in self._records:
            if r.id == memory_id:
                return r
        raise RecordNotFound(f"MemoryRecord {memory_id}")

    def deprecate(self, memory: MemoryRecord) -> None:
        pass

    def list_by_type(self, memory_type: MemoryType) -> Sequence[MemoryRecord]:
        return [r for r in self._records if r.type == memory_type]

    def search(self, criteria: MemorySearchCriteria) -> Sequence[MemoryRecord]:
        self.last_criteria = criteria
        return list(self._records)


class FakeAuditLogReader:
    """Fake AuditLogReader returning a pre-configured page."""

    def __init__(self, page: AuditLogPage | None = None) -> None:
        self._page = page or AuditLogPage(events=(), corrupt_count=0, files_scanned=0, has_more=False)
        self.last_query: AuditLogQuery | None = None
        self.called = False

    def read(self, query: AuditLogQuery) -> AuditLogPage:
        self.last_query = query
        self.called = True
        return self._page


class FakeTaskRepository:
    def __init__(self, tasks: dict | None = None) -> None:
        self._tasks: dict[str, object] = dict(tasks or {})

    def get(self, task_id: TaskId) -> object:
        if task_id.value not in self._tasks:
            raise RecordNotFound(f"Task {task_id}")
        return self._tasks[task_id.value]

    def add(self, task: object) -> None:
        pass

    def update(self, task: object) -> None:
        pass

    def list(self) -> Sequence[object]:
        return list(self._tasks.values())

    def compare_and_set_status(self, task: object, *, expected: object) -> bool:
        return False


class FakeWorkflowRunRepository:
    def __init__(self, active_run: object = None) -> None:
        self._active = active_run

    def find_active_by_task(self, task_id: TaskId) -> object | None:
        return self._active

    def get(self, run_id: object) -> object:
        raise RecordNotFound("not found")

    def add(self, run: object) -> None:
        pass

    def update(self, run: object) -> None:
        pass

    def compare_and_set_status(self, run: object, *, expected: object) -> bool:
        return False


class FakeWorkerRunRepository:
    def __init__(self, runs: list | None = None) -> None:
        self._runs: list[object] = list(runs or [])

    def get(self, worker_run_id: WorkerRunId) -> object:
        for r in self._runs:
            if r.id == worker_run_id:  # type: ignore[union-attr]
                return r
        raise RecordNotFound(f"WorkerRun {worker_run_id}")

    def add(self, run: object) -> None:
        pass

    def update(self, run: object) -> None:
        pass

    def list_by_task(self, task_id: TaskId) -> Sequence[object]:
        return [r for r in self._runs if r.task_id == task_id]  # type: ignore[union-attr]


class FakeEnergyRepository:
    def __init__(self, records: list[EnergyUsage] | None = None) -> None:
        self._records = list(records or [])

    def append(self, usage: EnergyUsage) -> None:
        self._records.append(usage)

    def get(self, usage_id: EnergyUsageId) -> EnergyUsage:
        raise RecordNotFound("not found")

    def list_by_task(self, task_id: TaskId) -> Sequence[EnergyUsage]:
        return [r for r in self._records if r.task_id == task_id]

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[EnergyUsage]:
        return [r for r in self._records if r.worker_run_id == worker_run_id]


class FakeApprovalRepository:
    def __init__(self, approvals: list | None = None) -> None:
        self._approvals: list[object] = list(approvals or [])

    def add(self, approval: object) -> None:
        pass

    def resolve(self, approval: object) -> None:
        pass

    def get(self, approval_id: object) -> object:
        raise RecordNotFound("not found")

    def list_by_task(self, task_id: TaskId) -> Sequence[object]:
        return [a for a in self._approvals if a.task_id == task_id]  # type: ignore[union-attr]

    def find_by_gate_instance(self, gate_instance_id: object) -> object | None:
        return None

    def find_pending_by_run(self, workflow_run_id: object) -> object | None:
        return None

    def resolve_with_version(self, approval: object, *, expected_version: int) -> bool:
        return False


class FakeEvidenceRepository:
    def __init__(self, evidence: list[ExecutionEvidence] | None = None) -> None:
        self._evidence = list(evidence or [])

    def append(self, evidence: ExecutionEvidence) -> None:
        pass

    def get(self, evidence_id: EvidenceId) -> ExecutionEvidence:
        raise RecordNotFound("not found")

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[ExecutionEvidence]:
        return [e for e in self._evidence if e.worker_run_id == worker_run_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mem_record(mem_id: str = "M-1") -> MemoryRecord:
    return MemoryRecord(
        id=MemoryId(mem_id),
        type=MemoryType.PROJECT_FACT,
        title="title",
        summary="summary",
        created_at=_ts(),
    )


def _energy(task_id: str = "T-1", worker_run_id: str | None = None) -> EnergyUsage:
    return EnergyUsage(
        id=EnergyUsageId("EU-1"),
        tokens_in=TokenCount(100),
        tokens_out=TokenCount(200),
        created_at=_ts(),
        task_id=TaskId(task_id) if task_id else None,
        worker_run_id=WorkerRunId(worker_run_id) if worker_run_id else None,
    )


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


class FailAuditSink:
    def write(self, event: AuditEvent) -> None:
        raise RuntimeError("audit sink failed")


# ---------------------------------------------------------------------------
# SearchMemory: limit resolution
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
# SearchMemory: validation errors
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
# SearchMemory: typed criteria conversion
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
# SearchMemory: result
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
# SearchMemory: audit event
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
    detail_str = str(detail)
    assert "title" not in detail_str
    assert "summary" not in detail_str


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


# ---------------------------------------------------------------------------
# GetTaskLogs
# ---------------------------------------------------------------------------


def test_get_task_logs_omitted_limit_uses_default() -> None:
    from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT

    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    svc.query()
    assert reader.last_query is not None
    assert reader.last_query.limit == LOG_DEFAULT_LIMIT


def test_get_task_logs_explicit_limit_passed() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    svc.query(limit=10)
    assert reader.last_query is not None
    assert reader.last_query.limit == 10


def test_get_task_logs_zero_limit_raises() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError, match="positive"):
        svc.query(limit=0)


def test_get_task_logs_negative_limit_raises() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError, match="positive"):
        svc.query(limit=-5)


def test_get_task_logs_over_max_raises() -> None:
    from ant_orchestrator.config.constants import LOG_MAX_LIMIT

    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError, match="exceeds maximum"):
        svc.query(limit=LOG_MAX_LIMIT + 1)


def test_get_task_logs_reader_not_called_on_validation_fail() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError):
        svc.query(limit=0)
    assert not reader.called


def test_get_task_logs_since_passed_to_reader() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    since_str = "2026-06-20T00:00:00+00:00"
    svc.query(since=since_str)
    assert reader.last_query is not None
    assert reader.last_query.since is not None
    assert reader.last_query.since.tzinfo is not None


def test_get_task_logs_naive_since_raises() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError, match="timezone-aware"):
        svc.query(since="2026-06-20T00:00:00")


def test_get_task_logs_invalid_since_raises() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    with pytest.raises(DomainError, match="invalid since"):
        svc.query(since="not-a-date")


def test_get_task_logs_metadata_preserved() -> None:
    page = AuditLogPage(events=(), corrupt_count=3, files_scanned=2, has_more=True)
    reader = FakeAuditLogReader(page=page)
    svc = GetTaskLogs(reader)
    result = svc.query()
    assert result.corrupt_count == 3
    assert result.files_scanned == 2
    assert result.has_more is True


def test_get_task_logs_task_id_passed() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    svc.query(task_id="TASK-1")
    assert reader.last_query is not None
    assert reader.last_query.task_id == "TASK-1"


def test_get_task_logs_empty_page() -> None:
    reader = FakeAuditLogReader()
    svc = GetTaskLogs(reader)
    result = svc.query()
    assert result.events == ()


# ---------------------------------------------------------------------------
# GetTaskDetail
# ---------------------------------------------------------------------------


def _make_task(task_id: str = "T-1") -> object:
    from ant_orchestrator.core.domain.entities import Task
    from ant_orchestrator.core.domain.enums import TaskPriority, TaskSource, TaskStatus

    return Task(
        id=TaskId(task_id),
        title="Test Task",
        status=TaskStatus.RUNNING,
        source=TaskSource.HUMAN,
        priority=TaskPriority.NORMAL,
        created_at=_ts(),
        updated_at=_ts(10),
    )


def _make_worker_run(worker_run_id: str = "WR-1", task_id: str = "T-1") -> object:
    from ant_orchestrator.core.domain.entities import WorkerRun
    from ant_orchestrator.core.domain.enums import WorkerRunStatus

    return WorkerRun(
        id=WorkerRunId(worker_run_id),
        task_id=TaskId(task_id),
        status=WorkerRunStatus.SUCCEEDED,
        created_at=_ts(),
    )


def test_get_task_detail_not_found_raises() -> None:
    svc = GetTaskDetail(
        task_repo=FakeTaskRepository(),
        workflow_run_repo=FakeWorkflowRunRepository(),
        worker_run_repo=FakeWorkerRunRepository(),
        energy_repo=FakeEnergyRepository(),
        approval_repo=FakeApprovalRepository(),
    )
    with pytest.raises(RecordNotFound):
        svc.get("NO-SUCH-TASK")


def test_get_task_detail_task_no_runs(database: object) -> None:
    task = _make_task()
    svc = GetTaskDetail(
        task_repo=FakeTaskRepository({"T-1": task}),
        workflow_run_repo=FakeWorkflowRunRepository(active_run=None),
        worker_run_repo=FakeWorkerRunRepository(),
        energy_repo=FakeEnergyRepository(),
        approval_repo=FakeApprovalRepository(),
    )
    view = svc.get("T-1")
    assert isinstance(view, TaskDetailView)
    assert view.task_id == "T-1"
    assert view.title == "Test Task"
    assert view.active_workflow_run is None
    assert view.worker_runs == ()
    assert view.energy_totals.tokens_in == 0
    assert view.approvals == ()


def test_get_task_detail_energy_aggregate() -> None:
    task = _make_task()
    eu1 = _energy("T-1")
    eu2 = EnergyUsage(
        id=EnergyUsageId("EU-2"),
        tokens_in=TokenCount(50),
        tokens_out=TokenCount(75),
        created_at=_ts(),
        task_id=TaskId("T-1"),
    )
    svc = GetTaskDetail(
        task_repo=FakeTaskRepository({"T-1": task}),
        workflow_run_repo=FakeWorkflowRunRepository(),
        worker_run_repo=FakeWorkerRunRepository(),
        energy_repo=FakeEnergyRepository(records=[eu1, eu2]),
        approval_repo=FakeApprovalRepository(),
    )
    view = svc.get("T-1")
    assert view.energy_totals.tokens_in == 150
    assert view.energy_totals.tokens_out == 275
    assert view.energy_totals.record_count == 2


def test_get_task_detail_worker_runs_listed() -> None:
    task = _make_task()
    wr = _make_worker_run()
    svc = GetTaskDetail(
        task_repo=FakeTaskRepository({"T-1": task}),
        workflow_run_repo=FakeWorkflowRunRepository(),
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(),
        approval_repo=FakeApprovalRepository(),
    )
    view = svc.get("T-1")
    assert len(view.worker_runs) == 1
    assert view.worker_runs[0].worker_run_id == "WR-1"
    assert view.worker_runs[0].status == "succeeded"


# ---------------------------------------------------------------------------
# GetWorkerRunDetail
# ---------------------------------------------------------------------------


def test_get_worker_run_detail_not_found_raises() -> None:
    svc = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(),
        energy_repo=FakeEnergyRepository(),
        evidence_repo=FakeEvidenceRepository(),
    )
    with pytest.raises(RecordNotFound):
        svc.get("NO-SUCH-RUN")


def test_get_worker_run_detail_basic() -> None:
    wr = _make_worker_run()
    svc = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(),
        evidence_repo=FakeEvidenceRepository(),
    )
    view = svc.get("WR-1")
    assert isinstance(view, WorkerRunDetailView)
    assert view.worker_run_id == "WR-1"
    assert view.task_id == "T-1"
    assert view.energy.tokens_in == 0
    assert view.evidence == ()


def test_get_worker_run_detail_energy_visible() -> None:
    wr = _make_worker_run()
    eu = _energy("T-1", worker_run_id="WR-1")
    svc = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(records=[eu]),
        evidence_repo=FakeEvidenceRepository(),
    )
    view = svc.get("WR-1")
    assert view.energy.tokens_in == 100
    assert view.energy.tokens_out == 200
    assert view.energy.record_count == 1


def test_get_worker_run_detail_evidence_listed() -> None:
    wr = _make_worker_run()
    ev = ExecutionEvidence(
        id=EvidenceId("EV-1"),
        worker_run_id=WorkerRunId("WR-1"),
        created_at=_ts(),
        files_read=("a.py", "b.py"),
        files_changed=("c.py",),
        commands=("pytest",),
        result="ok",
    )
    svc = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(),
        evidence_repo=FakeEvidenceRepository(evidence=[ev]),
    )
    view = svc.get("WR-1")
    assert len(view.evidence) == 1
    assert view.evidence[0].files_read_count == 2
    assert view.evidence[0].files_changed_count == 1
    assert view.evidence[0].commands_count == 1
    assert view.evidence[0].result == "ok"


# ---------------------------------------------------------------------------
# Import boundary: services must not import persistence or adapters
# ---------------------------------------------------------------------------


def test_search_memory_no_persistence_import() -> None:
    import ast
    import ant_orchestrator

    pkg = Path(ant_orchestrator.__file__).parent
    svc_file = pkg / "application" / "services" / "search_memory.py"
    tree = ast.parse(svc_file.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for mod in modules:
        assert not mod.startswith("ant_orchestrator.persistence"), (
            f"search_memory.py must not import persistence: {mod}"
        )
        assert not mod.startswith("ant_orchestrator.adapters"), (
            f"search_memory.py must not import adapters: {mod}"
        )


def test_get_task_detail_no_persistence_import() -> None:
    import ast
    import ant_orchestrator

    pkg = Path(ant_orchestrator.__file__).parent
    svc_file = pkg / "application" / "services" / "get_task_detail.py"
    tree = ast.parse(svc_file.read_text(encoding="utf-8"))
    modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    for mod in modules:
        assert not mod.startswith("ant_orchestrator.persistence"), (
            f"get_task_detail.py must not import persistence: {mod}"
        )
