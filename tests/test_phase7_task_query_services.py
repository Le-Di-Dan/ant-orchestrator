"""Phase 7 CP3 — GetTaskLogs, GetTaskDetail, GetWorkerRunDetail, import-boundary tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ant_orchestrator.application.models.execution_views import TaskDetailView, WorkerRunDetailView
from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage
from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.application.services.get_task_detail import GetTaskDetail
from ant_orchestrator.application.services.get_task_logs import GetTaskLogs
from ant_orchestrator.application.services.get_worker_run_detail import GetWorkerRunDetail
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT, LOG_MAX_LIMIT
from ant_orchestrator.core.domain.errors import DomainError
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from tests.support.fake_query_repos import (
    FakeApprovalRepository,
    FakeAuditLogReader,
    FakeEnergyRepository,
    FakeEvidenceRepository,
    FakeTaskRepository,
    FakeWorkerRunRepository,
    FakeWorkflowRunRepository,
)

_BASE_TS = datetime(2026, 6, 22, tzinfo=UTC)


def _ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


def _energy(task_id: str = "T-1", worker_run_id: str | None = None) -> EnergyUsage:
    return EnergyUsage(
        id=EnergyUsageId("EU-1"),
        tokens_in=TokenCount(100),
        tokens_out=TokenCount(200),
        created_at=_ts(),
        task_id=TaskId(task_id) if task_id else None,
        worker_run_id=WorkerRunId(worker_run_id) if worker_run_id else None,
    )


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


# ---------------------------------------------------------------------------
# GetTaskLogs
# ---------------------------------------------------------------------------


def test_get_task_logs_omitted_limit_uses_default() -> None:
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
    svc = GetTaskLogs(FakeAuditLogReader())
    with pytest.raises(DomainError, match="positive"):
        svc.query(limit=0)


def test_get_task_logs_negative_limit_raises() -> None:
    svc = GetTaskLogs(FakeAuditLogReader())
    with pytest.raises(DomainError, match="positive"):
        svc.query(limit=-5)


def test_get_task_logs_over_max_raises() -> None:
    svc = GetTaskLogs(FakeAuditLogReader())
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
    svc.query(since="2026-06-20T00:00:00+00:00")
    assert reader.last_query is not None
    assert reader.last_query.since is not None
    assert reader.last_query.since.tzinfo is not None


def test_get_task_logs_naive_since_raises() -> None:
    svc = GetTaskLogs(FakeAuditLogReader())
    with pytest.raises(DomainError, match="timezone-aware"):
        svc.query(since="2026-06-20T00:00:00")


def test_get_task_logs_invalid_since_raises() -> None:
    svc = GetTaskLogs(FakeAuditLogReader())
    with pytest.raises(DomainError, match="invalid since"):
        svc.query(since="not-a-date")


def test_get_task_logs_metadata_preserved() -> None:
    page = AuditLogPage(events=(), corrupt_count=3, files_scanned=2, has_more=True)
    reader = FakeAuditLogReader(page=page)
    result = GetTaskLogs(reader).query()
    assert result.corrupt_count == 3
    assert result.files_scanned == 2
    assert result.has_more is True


def test_get_task_logs_task_id_passed() -> None:
    reader = FakeAuditLogReader()
    GetTaskLogs(reader).query(task_id="TASK-1")
    assert reader.last_query is not None
    assert reader.last_query.task_id == "TASK-1"


def test_get_task_logs_empty_page() -> None:
    result = GetTaskLogs(FakeAuditLogReader()).query()
    assert result.events == ()


# ---------------------------------------------------------------------------
# GetTaskDetail
# ---------------------------------------------------------------------------


def _detail_svc(**kwargs: object) -> GetTaskDetail:
    defaults: dict[str, object] = {
        "task_repo": FakeTaskRepository(),
        "workflow_run_repo": FakeWorkflowRunRepository(),
        "worker_run_repo": FakeWorkerRunRepository(),
        "energy_repo": FakeEnergyRepository(),
        "approval_repo": FakeApprovalRepository(),
    }
    defaults.update(kwargs)
    return GetTaskDetail(**defaults)  # type: ignore[arg-type]


def test_get_task_detail_not_found_raises() -> None:
    with pytest.raises(RecordNotFound):
        _detail_svc().get("NO-SUCH-TASK")


def test_get_task_detail_task_no_runs() -> None:
    task = _make_task()
    view = _detail_svc(task_repo=FakeTaskRepository({"T-1": task})).get("T-1")
    assert isinstance(view, TaskDetailView)
    assert view.task_id == "T-1"
    assert view.title == "Test Task"
    assert view.active_workflow_run is None
    assert view.worker_runs == ()
    assert view.energy_totals.tokens_in == 0
    assert view.approvals == ()


def test_get_task_detail_energy_aggregate() -> None:
    task = _make_task()
    eu2 = EnergyUsage(
        id=EnergyUsageId("EU-2"),
        tokens_in=TokenCount(50),
        tokens_out=TokenCount(75),
        created_at=_ts(),
        task_id=TaskId("T-1"),
    )
    view = _detail_svc(
        task_repo=FakeTaskRepository({"T-1": task}),
        energy_repo=FakeEnergyRepository(records=[_energy("T-1"), eu2]),
    ).get("T-1")
    assert view.energy_totals.tokens_in == 150
    assert view.energy_totals.tokens_out == 275
    assert view.energy_totals.record_count == 2


def test_get_task_detail_worker_runs_listed() -> None:
    task = _make_task()
    wr = _make_worker_run()
    view = _detail_svc(
        task_repo=FakeTaskRepository({"T-1": task}),
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
    ).get("T-1")
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
    view = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(),
        evidence_repo=FakeEvidenceRepository(),
    ).get("WR-1")
    assert isinstance(view, WorkerRunDetailView)
    assert view.worker_run_id == "WR-1"
    assert view.task_id == "T-1"
    assert view.energy.tokens_in == 0
    assert view.evidence == ()


def test_get_worker_run_detail_energy_visible() -> None:
    wr = _make_worker_run()
    view = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(records=[_energy("T-1", worker_run_id="WR-1")]),
        evidence_repo=FakeEvidenceRepository(),
    ).get("WR-1")
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
    view = GetWorkerRunDetail(
        worker_run_repo=FakeWorkerRunRepository(runs=[wr]),
        energy_repo=FakeEnergyRepository(),
        evidence_repo=FakeEvidenceRepository(evidence=[ev]),
    ).get("WR-1")
    assert len(view.evidence) == 1
    assert view.evidence[0].files_read_count == 2
    assert view.evidence[0].files_changed_count == 1
    assert view.evidence[0].commands_count == 1
    assert view.evidence[0].result == "ok"


# ---------------------------------------------------------------------------
# Import boundary
# ---------------------------------------------------------------------------


def test_search_memory_no_persistence_import() -> None:
    import ast
    import ant_orchestrator

    pkg = Path(ant_orchestrator.__file__).parent
    svc_file = pkg / "application" / "services" / "search_memory.py"
    tree = ast.parse(svc_file.read_text(encoding="utf-8"))
    modules = {
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    for mod in modules:
        assert not mod.startswith("ant_orchestrator.persistence")
        assert not mod.startswith("ant_orchestrator.adapters")


def test_get_task_detail_no_persistence_import() -> None:
    import ast
    import ant_orchestrator

    pkg = Path(ant_orchestrator.__file__).parent
    svc_file = pkg / "application" / "services" / "get_task_detail.py"
    tree = ast.parse(svc_file.read_text(encoding="utf-8"))
    modules = {
        n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module
    }
    for mod in modules:
        assert not mod.startswith("ant_orchestrator.persistence")
