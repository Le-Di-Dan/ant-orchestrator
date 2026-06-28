"""CP6 restart — find_recoverable_window3 unit-level guard tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1", run_id: str = "R1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("setup"))
    return db


def _uow_factory(db: Database):  # type: ignore[no-untyped-def]
    return lambda: SqliteUnitOfWork(db)


# ---------------------------------------------------------------------------
# find_recoverable_window3 — unit-level guard
# ---------------------------------------------------------------------------


def test_find_recoverable_window3_none_if_no_attempts(tmp_path: Path) -> None:
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    result = orch.find_recoverable_window3("R1", "T1-test")
    assert result is None


def test_find_recoverable_window3_none_if_active_attempt_exists(tmp_path: Path) -> None:
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    orch.before_execute("R1", "T1-test")  # creates STARTED
    result = orch.find_recoverable_window3("R1", "T1-test")
    assert result is None  # active attempt → not Window 3
