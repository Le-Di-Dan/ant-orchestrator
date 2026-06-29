"""CP4 GetTaskResult application service tests.

Covers:
- Task exists + result ready → returns TaskResultView.
- Task exists + result not yet final → returns None.
- Task does not exist → raises RecordNotFound.
- View fields are correctly mapped.
- Artifact refs appear in view.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.application.services.get_task_result import GetTaskResult
from ant_orchestrator.config.constants import ARTIFACT_SHA256_HEX_LENGTH, TASK_RESULT_VERSION
from ant_orchestrator.core.domain.task_result import (
    ArtifactKind,
    ArtifactRef,
    ArtifactState,
    TaskResult,
    TaskResultOutcome,
    make_result_id,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from ant_orchestrator.persistence.repositories.task_result import SqliteTaskResultRepository
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

_TS = UtcTimestamp(datetime(2026, 6, 29, tzinfo=UTC))
_NOW_ISO = "2026-06-29T00:00:00+00:00"
_DIGEST = "c" * ARTIFACT_SHA256_HEX_LENGTH


def _clock() -> FakeClock:
    return FakeClock(_TS)


def _bootstrap(tmp_path: Path, task_id: str, run_id: str) -> Database:
    clock = _clock()
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("ID"))
    return db


def _make_service(db: Database) -> GetTaskResult:
    return GetTaskResult(
        task_repo=SqliteTaskRepository(db),
        result_repo=SqliteTaskResultRepository(db),
    )


def _save_result(db: Database, task_id: str, run_id: str) -> None:
    result = TaskResult(
        result_id=make_result_id(run_id, "completed"),
        task_id=task_id,
        workflow_run_id=run_id,
        outcome=TaskResultOutcome.COMPLETED,
        summary="Summary from service test.",
        artifact_refs=(
            ArtifactRef(
                artifact_id="art-001",
                kind=ArtifactKind.INTERNAL,
                relative_path="results/out.json",
                media_type="application/json",
                sha256=_DIGEST,
                size_bytes=64,
                created_by_attempt_id=None,
                state=ArtifactState.FINAL,
                metadata="{}",
            ),
        ),
        failure=None,
        finalized_at=_TS,
        result_version=TASK_RESULT_VERSION,
    )
    SqliteTaskResultRepository(db).save(result, artifact_created_at=_NOW_ISO)


# ---------------------------------------------------------------------------
# Ready result
# ---------------------------------------------------------------------------


def test_get_ready_result(tmp_path: Path) -> None:
    db = _bootstrap(tmp_path, "task-1", "run-1")
    _save_result(db, "task-1", "run-1")
    svc = _make_service(db)
    view = svc.get("task-1")
    assert view is not None
    assert view.task_id == "task-1"
    assert view.workflow_run_id == "run-1"
    assert view.outcome == "completed"
    assert view.summary == "Summary from service test."
    assert view.failure is None
    assert view.result_version == TASK_RESULT_VERSION


def test_get_result_contains_artifacts(tmp_path: Path) -> None:
    db = _bootstrap(tmp_path, "task-1", "run-1")
    _save_result(db, "task-1", "run-1")
    svc = _make_service(db)
    view = svc.get("task-1")
    assert view is not None
    assert len(view.artifact_refs) == 1
    ref = view.artifact_refs[0]
    assert ref.artifact_id == "art-001"
    assert ref.kind == "internal"
    assert ref.sha256 == _DIGEST
    assert ref.state == "final"


# ---------------------------------------------------------------------------
# Pending result (task exists, result not finalized)
# ---------------------------------------------------------------------------


def test_get_pending_result_returns_none(tmp_path: Path) -> None:
    db = _bootstrap(tmp_path, "task-1", "run-1")
    # No result saved
    svc = _make_service(db)
    view = svc.get("task-1")
    assert view is None


# ---------------------------------------------------------------------------
# Unknown task
# ---------------------------------------------------------------------------


def test_get_unknown_task_raises(tmp_path: Path) -> None:
    clock = _clock()
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    svc = _make_service(db)
    with pytest.raises(RecordNotFound):
        svc.get("nonexistent-task")
