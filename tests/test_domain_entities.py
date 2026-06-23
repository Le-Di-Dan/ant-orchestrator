"""Unit tests for domain entities (CP2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.core.domain.entities import Task, WorkerRun
from ant_orchestrator.core.domain.enums import (
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import (
    TaskId,
    UtcTimestamp,
    WorkerRunId,
)

T0 = UtcTimestamp(datetime(2026, 6, 22, 0, 0, tzinfo=UTC))
T1 = UtcTimestamp(datetime(2026, 6, 22, 1, 0, tzinfo=UTC))


def _task() -> Task:
    return Task(
        id=TaskId("TASK-1"),
        title="demo",
        status=TaskStatus.CREATED,
        source=TaskSource.HUMAN,
        priority=TaskPriority.NORMAL,
        created_at=T0,
        updated_at=T0,
    )


def test_task_rejects_empty_title() -> None:
    with pytest.raises(InvariantViolation):
        Task(
            id=TaskId("TASK-1"),
            title="",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=T0,
            updated_at=T0,
        )


def test_task_rejects_updated_before_created() -> None:
    earlier = UtcTimestamp(datetime(2026, 6, 21, tzinfo=UTC))
    with pytest.raises(InvariantViolation):
        Task(
            id=TaskId("TASK-1"),
            title="demo",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=T0,
            updated_at=earlier,
        )


def test_task_with_status_returns_new_instance() -> None:
    task = _task()
    updated = task.with_status(TaskStatus.RUNNING, now=T1)
    assert updated is not task
    assert updated.status is TaskStatus.RUNNING
    assert updated.updated_at == T1
    assert task.status is TaskStatus.CREATED  # original unchanged


def test_worker_run_with_status_sets_finished() -> None:
    run = WorkerRun(
        id=WorkerRunId("RUN-1"),
        task_id=TaskId("TASK-1"),
        status=WorkerRunStatus.RUNNING,
        created_at=T0,
        started_at=T0,
    )
    done = run.with_status(WorkerRunStatus.SUCCEEDED, finished_at=T1)
    assert done.status is WorkerRunStatus.SUCCEEDED
    assert done.finished_at == T1
    assert done.started_at == T0  # preserved
    assert run.finished_at is None


def test_worker_run_with_status_preserves_when_omitted() -> None:
    run = WorkerRun(
        id=WorkerRunId("RUN-1"),
        task_id=TaskId("TASK-1"),
        status=WorkerRunStatus.PENDING,
        created_at=T0,
    )
    started = run.with_status(WorkerRunStatus.RUNNING, started_at=T1)
    assert started.started_at == T1
    assert started.finished_at is None


def test_task_created_equals_updated_is_allowed() -> None:
    assert _task().created_at == T0


def test_worker_run_default_timestamps_none() -> None:
    run = WorkerRun(
        id=WorkerRunId("RUN-1"),
        task_id=TaskId("TASK-1"),
        status=WorkerRunStatus.PENDING,
        created_at=T0,
    )
    assert run.started_at is None
    assert run.finished_at is None
