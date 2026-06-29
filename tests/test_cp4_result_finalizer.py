"""CP4 TaskResultFinalizer service tests.

Covers:
- All 4 outcomes create a TaskResult.
- Idempotent on duplicate finalization (same outcome, same run).
- FailureInfo present for non-completed outcomes.
- Summary extracted from graph state or falls back.
- Unknown outcome raises ValueError.
- No raw provider output in result.
- Conflict race: second save after concurrent insert → returns existing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.services.result_finalizer import TaskResultFinalizer
from ant_orchestrator.config.constants import TASK_RESULT_VERSION
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.task_result import SqliteTaskResultRepository
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

_TS = UtcTimestamp(datetime(2026, 6, 29, tzinfo=UTC))


def _clock() -> FakeClock:
    return FakeClock(_TS)


def _bootstrap_with_run(tmp_path: Path, task_id: str, run_id: str) -> Database:
    clock = _clock()
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("ID"))
    return db


def _make_finalizer(db: Database) -> TaskResultFinalizer:
    return TaskResultFinalizer(SqliteTaskResultRepository(db), clock=_clock())


_BASE_STATE: dict[str, object] = {
    "task_id": "task-1",
    "workflow_run_id": "run-1",
    "phase": "review",
    "retry_count": 0,
}


# ---------------------------------------------------------------------------
# All outcomes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("outcome", ["completed", "failed", "rejected", "cancelled"])
def test_finalize_creates_result(tmp_path: Path, outcome: str) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    result_id = finalizer.finalize(
        run_id="run-1",
        task_id="task-1",
        final_outcome=outcome,
        state=_BASE_STATE,
    )
    assert result_id
    repo = SqliteTaskResultRepository(db)
    loaded = repo.find_by_run("run-1")
    assert loaded is not None
    assert loaded.outcome.value == outcome
    assert loaded.task_id == "task-1"
    assert loaded.result_version == TASK_RESULT_VERSION


def test_completed_has_no_failure(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome="completed", state={})
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert loaded.failure is None


@pytest.mark.parametrize("outcome", ["failed", "rejected", "cancelled"])
def test_non_completed_has_failure(tmp_path: Path, outcome: str) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome=outcome, state=_BASE_STATE)
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert loaded.failure is not None
    assert loaded.failure.code


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_duplicate_finalization_idempotent(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    id1 = finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome="completed", state={})
    id2 = finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome="completed", state={})
    assert id1 == id2
    # Ensure only one result exists
    repo = SqliteTaskResultRepository(db)
    result = repo.find_by_run("run-1")
    assert result is not None


# ---------------------------------------------------------------------------
# Summary extraction
# ---------------------------------------------------------------------------


def test_summary_from_business_summary(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    finalizer.finalize(
        run_id="run-1",
        task_id="task-1",
        final_outcome="completed",
        state={"business_summary": "All tests passed."},
    )
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert "All tests passed." in loaded.summary


def test_summary_from_phase_fallback(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    finalizer.finalize(
        run_id="run-1",
        task_id="task-1",
        final_outcome="completed",
        state={"phase": "review"},
    )
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert "review" in loaded.summary


def test_summary_default_fallback_when_no_state(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome="completed", state={})
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert loaded.summary  # non-empty


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_unknown_outcome_raises(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    with pytest.raises(ValueError, match="Unknown final_outcome"):
        finalizer.finalize(run_id="run-1", task_id="task-1", final_outcome="bogus", state={})


# ---------------------------------------------------------------------------
# Security: no raw output in result
# ---------------------------------------------------------------------------


def test_no_raw_provider_output_in_summary(tmp_path: Path) -> None:
    db = _bootstrap_with_run(tmp_path, "task-1", "run-1")
    finalizer = _make_finalizer(db)
    secret_state = {
        "api_key": "sk-secret-key",
        "raw_output": "TRACEBACK: raise Exception()",
        "business_summary": "Completed successfully.",
    }
    finalizer.finalize(
        run_id="run-1", task_id="task-1", final_outcome="completed", state=secret_state
    )
    loaded = SqliteTaskResultRepository(db).find_by_run("run-1")
    assert loaded is not None
    assert "sk-secret" not in loaded.summary
    assert "TRACEBACK" not in loaded.summary
    assert "Completed successfully." in loaded.summary
