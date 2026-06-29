"""CP4 persistence tests: migration v5, repository round-trip, idempotency.

Covers:
- Fresh database created at v5 directly (no migration needed).
- Upgrade from v4 to v5.
- Migration idempotency (run v5 migration twice).
- Result save/load round-trip.
- find_by_task and find_by_run.
- Duplicate finalization same outcome → ResultConflict.
- Artifact refs persisted and loaded.
- FailureInfo round-trip.
- Schema inspector detects v5.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.database import ResultConflict
from ant_orchestrator.config.constants import ARTIFACT_SHA256_HEX_LENGTH, TASK_RESULT_VERSION
from ant_orchestrator.core.domain.task_result import (
    ArtifactKind,
    ArtifactRef,
    ArtifactState,
    FailureInfo,
    TaskResult,
    TaskResultOutcome,
    make_result_id,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migration_v4 import SqliteDatabaseMigratorV4
from ant_orchestrator.persistence.migration_v5 import SqliteDatabaseMigratorV5
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
from ant_orchestrator.persistence.repositories.task_result import SqliteTaskResultRepository
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

_TS = UtcTimestamp(datetime(2026, 6, 29, tzinfo=UTC))
_NOW_ISO = "2026-06-29T00:00:00+00:00"
_DIGEST = "b" * ARTIFACT_SHA256_HEX_LENGTH


def _clock() -> FakeClock:
    return FakeClock(_TS)


def _id_gen() -> SequentialIdGenerator:
    return SequentialIdGenerator("ID")


def _bootstrap(tmp_path: Path) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(_clock()).bootstrap(db_path)
    return Database(db_path)


def _setup(tmp_path: Path, task_id: str, run_id: str) -> Database:
    """Bootstrap DB, create task and workflow_run (satisfies FK constraints)."""
    clock = _clock()
    db = _bootstrap(tmp_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, _id_gen())
    return db


def _make_result(
    task_id: str,
    run_id: str,
    outcome: TaskResultOutcome = TaskResultOutcome.COMPLETED,
    *,
    with_artifact: bool = False,
    with_failure: bool = False,
) -> TaskResult:
    failure = None
    if with_failure or outcome is not TaskResultOutcome.COMPLETED:
        failure = FailureInfo(
            code=outcome.value, message="test failure", retryable=False, source="test"
        )
    artifacts: tuple[ArtifactRef, ...] = ()
    if with_artifact:
        artifacts = (
            ArtifactRef(
                artifact_id="art-001",
                kind=ArtifactKind.INTERNAL,
                relative_path="results/out.json",
                media_type="application/json",
                sha256=_DIGEST,
                size_bytes=128,
                created_by_attempt_id="att-001",
                state=ArtifactState.FINAL,
                metadata="{}",
            ),
        )
    return TaskResult(
        result_id=make_result_id(run_id, outcome.value),
        task_id=task_id,
        workflow_run_id=run_id,
        outcome=outcome,
        summary="Test summary.",
        artifact_refs=artifacts,
        failure=failure,
        finalized_at=_TS,
        result_version=TASK_RESULT_VERSION,
    )


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------


def test_fresh_database_at_v5(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    version = SqliteDatabaseInspector().schema_version(tmp_path / "state.sqlite")
    assert version == 5


def test_upgrade_v4_to_v5(tmp_path: Path) -> None:
    from tests.support.legacy_schema_v3 import build_v3_database

    db_path = tmp_path / "state.sqlite"
    build_v3_database(db_path)
    SqliteDatabaseMigratorV4(_clock()).migrate(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 4
    SqliteDatabaseMigratorV5(_clock()).migrate(db_path)
    assert SqliteDatabaseInspector().schema_version(db_path) == 5


def test_v5_migration_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "state.sqlite"
    _bootstrap(tmp_path)  # already at v5
    SqliteDatabaseMigratorV5(_clock()).migrate(db_path)  # no-op
    assert SqliteDatabaseInspector().schema_version(db_path) == 5


def test_bootstrap_reopen(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    db2 = Database(tmp_path / "state.sqlite")
    repo = SqliteTaskResultRepository(db2)
    assert repo.find_by_task("nonexistent") is None


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_save_and_find_by_run(tmp_path: Path) -> None:
    db = _setup(tmp_path, "task-1", "run-1")
    repo = SqliteTaskResultRepository(db)
    result = _make_result("task-1", "run-1")
    repo.save(result, artifact_created_at=_NOW_ISO)
    loaded = repo.find_by_run("run-1")
    assert loaded is not None
    assert loaded.outcome is TaskResultOutcome.COMPLETED
    assert loaded.summary == "Test summary."
    assert loaded.task_id == "task-1"
    assert loaded.workflow_run_id == "run-1"
    assert loaded.result_version == TASK_RESULT_VERSION


def test_save_and_find_by_task(tmp_path: Path) -> None:
    db = _setup(tmp_path, "task-1", "run-1")
    repo = SqliteTaskResultRepository(db)
    result = _make_result("task-1", "run-1")
    repo.save(result, artifact_created_at=_NOW_ISO)
    loaded = repo.find_by_task("task-1")
    assert loaded is not None
    assert loaded.outcome is TaskResultOutcome.COMPLETED


def test_find_by_run_missing(tmp_path: Path) -> None:
    db = _bootstrap(tmp_path)
    repo = SqliteTaskResultRepository(db)
    assert repo.find_by_run("nonexistent") is None


def test_find_by_task_missing(tmp_path: Path) -> None:
    db = _bootstrap(tmp_path)
    repo = SqliteTaskResultRepository(db)
    assert repo.find_by_task("nonexistent") is None


def test_failure_info_round_trip(tmp_path: Path) -> None:
    db = _setup(tmp_path, "task-1", "run-1")
    repo = SqliteTaskResultRepository(db)
    result = _make_result("task-1", "run-1", TaskResultOutcome.FAILED, with_failure=True)
    repo.save(result, artifact_created_at=_NOW_ISO)
    loaded = repo.find_by_run("run-1")
    assert loaded is not None
    assert loaded.failure is not None
    assert loaded.failure.code == "failed"
    assert loaded.failure.message == "test failure"
    assert loaded.failure.retryable is False
    assert loaded.failure.source == "test"


def test_artifact_refs_round_trip(tmp_path: Path) -> None:
    db = _setup(tmp_path, "task-1", "run-1")
    repo = SqliteTaskResultRepository(db)
    result = _make_result("task-1", "run-1", with_artifact=True)
    repo.save(result, artifact_created_at=_NOW_ISO)
    loaded = repo.find_by_run("run-1")
    assert loaded is not None
    assert len(loaded.artifact_refs) == 1
    ref = loaded.artifact_refs[0]
    assert ref.artifact_id == "art-001"
    assert ref.kind is ArtifactKind.INTERNAL
    assert ref.sha256 == _DIGEST
    assert ref.size_bytes == 128
    assert ref.state is ArtifactState.FINAL


# ---------------------------------------------------------------------------
# Idempotency and conflict
# ---------------------------------------------------------------------------


def test_duplicate_finalization_raises_conflict(tmp_path: Path) -> None:
    db = _setup(tmp_path, "task-1", "run-1")
    repo = SqliteTaskResultRepository(db)
    result = _make_result("task-1", "run-1")
    repo.save(result, artifact_created_at=_NOW_ISO)
    with pytest.raises(ResultConflict):
        repo.save(result, artifact_created_at=_NOW_ISO)


def test_different_task_different_run_no_conflict(tmp_path: Path) -> None:
    clock = _clock()
    ids = _id_gen()
    db = _bootstrap(tmp_path)
    add_task(db, "task-1", clock=clock)
    add_task(db, "task-2", clock=clock)
    create_running_run(db, WorkflowRunId("run-1"), "task-1", clock, ids)
    create_running_run(db, WorkflowRunId("run-2"), "task-2", clock, ids)
    repo = SqliteTaskResultRepository(db)
    r1 = _make_result("task-1", "run-1")
    r2 = _make_result("task-2", "run-2")
    repo.save(r1, artifact_created_at=_NOW_ISO)
    repo.save(r2, artifact_created_at=_NOW_ISO)
    assert repo.find_by_run("run-1") is not None
    assert repo.find_by_run("run-2") is not None


def test_all_outcomes_persisted(tmp_path: Path) -> None:
    clock = _clock()
    ids = _id_gen()
    db = _bootstrap(tmp_path)
    for i, outcome in enumerate(TaskResultOutcome):
        task_id = f"task-{i}"
        run_id = f"run-{i}"
        add_task(db, task_id, clock=clock)
        create_running_run(db, WorkflowRunId(run_id), task_id, clock, ids)
        repo = SqliteTaskResultRepository(db)
        r = _make_result(task_id, run_id, outcome)
        repo.save(r, artifact_created_at=_NOW_ISO)
        loaded = repo.find_by_run(f"run-{i}")
        assert loaded is not None
        assert loaded.outcome is outcome
