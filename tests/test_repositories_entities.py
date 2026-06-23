"""Round-trip tests for entity/checkpoint/approval repositories (CP6)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.database import RecordNotFound, StorageIntegrityError
from ant_orchestrator.core.domain.entities import Task, WorkerRun
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.errors import ApprovalAlreadyResolved
from ant_orchestrator.core.domain.records import Approval, EnergyUsage, WorkflowCheckpoint
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    CheckpointId,
    EnergyUsageId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.approval import SqliteApprovalRepository
from ant_orchestrator.persistence.repositories.checkpoint import SqliteCheckpointRepository
from ant_orchestrator.persistence.repositories.energy_usage import SqliteEnergyUsageRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from ant_orchestrator.persistence.repositories.worker_run import SqliteWorkerRunRepository
from ant_orchestrator.persistence.serialization import dump_payload

TS = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))
TS2 = UtcTimestamp(datetime(2026, 6, 22, 1, tzinfo=UTC))


def _task(task_id: str = "TASK-1") -> Task:
    return Task(
        id=TaskId(task_id),
        title="demo",
        status=TaskStatus.CREATED,
        source=TaskSource.HUMAN,
        priority=TaskPriority.NORMAL,
        created_at=TS,
        updated_at=TS,
    )


def _seed_task(database: Database, task_id: str = "TASK-1") -> Task:
    task = _task(task_id)
    SqliteTaskRepository(database).add(task)
    return task


def test_task_round_trip_and_update(database: Database) -> None:
    repo = SqliteTaskRepository(database)
    repo.add(_task())
    assert repo.get(TaskId("TASK-1")).title == "demo"
    repo.update(_task().with_status(TaskStatus.RUNNING, now=TS2))
    assert repo.get(TaskId("TASK-1")).status is TaskStatus.RUNNING
    assert len(repo.list()) == 1


def test_task_get_missing(database: Database) -> None:
    with pytest.raises(RecordNotFound):
        SqliteTaskRepository(database).get(TaskId("nope"))


def test_worker_run_round_trip(database: Database) -> None:
    _seed_task(database)
    repo = SqliteWorkerRunRepository(database)
    run = WorkerRun(
        id=WorkerRunId("RUN-1"),
        task_id=TaskId("TASK-1"),
        status=WorkerRunStatus.RUNNING,
        created_at=TS,
        started_at=TS,
    )
    repo.add(run)
    repo.update(run.with_status(WorkerRunStatus.SUCCEEDED, finished_at=TS2))
    fetched = repo.get(WorkerRunId("RUN-1"))
    assert fetched.status is WorkerRunStatus.SUCCEEDED
    assert fetched.finished_at == TS2
    assert len(repo.list_by_task(TaskId("TASK-1"))) == 1


def test_worker_run_fk_enforced(database: Database) -> None:
    repo = SqliteWorkerRunRepository(database)
    orphan = WorkerRun(
        id=WorkerRunId("RUN-1"),
        task_id=TaskId("MISSING"),
        status=WorkerRunStatus.PENDING,
        created_at=TS,
    )
    with pytest.raises(sqlite3.IntegrityError):
        repo.add(orphan)


def test_energy_usage_round_trip_and_lists(database: Database) -> None:
    _seed_task(database)
    SqliteWorkerRunRepository(database).add(
        WorkerRun(
            id=WorkerRunId("RUN-1"),
            task_id=TaskId("TASK-1"),
            status=WorkerRunStatus.RUNNING,
            created_at=TS,
        )
    )
    repo = SqliteEnergyUsageRepository(database)
    usage = EnergyUsage(
        id=EnergyUsageId("E-1"),
        tokens_in=TokenCount(10),
        tokens_out=TokenCount(5),
        created_at=TS,
        task_id=TaskId("TASK-1"),
        worker_run_id=WorkerRunId("RUN-1"),
    )
    repo.append(usage)
    assert repo.get(EnergyUsageId("E-1")).tokens_in.value == 10
    assert len(repo.list_by_task(TaskId("TASK-1"))) == 1
    assert len(repo.list_by_worker_run(WorkerRunId("RUN-1"))) == 1


def test_energy_usage_ownership_mismatch(database: Database) -> None:
    _seed_task(database, "TASK-1")
    _seed_task(database, "TASK-2")
    SqliteWorkerRunRepository(database).add(
        WorkerRun(
            id=WorkerRunId("RUN-1"),
            task_id=TaskId("TASK-2"),
            status=WorkerRunStatus.RUNNING,
            created_at=TS,
        )
    )
    repo = SqliteEnergyUsageRepository(database)
    bad = EnergyUsage(
        id=EnergyUsageId("E-1"),
        tokens_in=TokenCount(1),
        tokens_out=TokenCount(1),
        created_at=TS,
        task_id=TaskId("TASK-1"),
        worker_run_id=WorkerRunId("RUN-1"),
    )
    with pytest.raises(StorageIntegrityError):
        repo.append(bad)


def test_checkpoint_round_trip_and_latest(database: Database) -> None:
    _seed_task(database)
    repo = SqliteCheckpointRepository(database)
    repo.append(
        WorkflowCheckpoint(
            id=CheckpointId("CK-1"),
            task_id=TaskId("TASK-1"),
            payload_version=1,
            payload={"b": 2, "a": 1},
            created_at=TS,
        )
    )
    repo.append(
        WorkflowCheckpoint(
            id=CheckpointId("CK-2"),
            task_id=TaskId("TASK-1"),
            payload_version=1,
            payload={"x": 9},
            created_at=TS2,
        )
    )
    assert repo.get(CheckpointId("CK-1")).payload == {"a": 1, "b": 2}
    assert repo.get_latest_by_task(TaskId("TASK-1")).id == CheckpointId("CK-2")
    assert len(repo.list_by_task(TaskId("TASK-1"))) == 2


def test_checkpoint_canonical_serialization_is_stable() -> None:
    assert dump_payload({"b": 2, "a": 1}) == dump_payload({"a": 1, "b": 2})


def _pending(approval_id: str = "AP-1") -> Approval:
    return Approval(
        id=ApprovalId(approval_id),
        task_id=TaskId("TASK-1"),
        status=ApprovalStatus.PENDING,
        requested_at=TS,
    )


def test_approval_add_resolve_round_trip(database: Database) -> None:
    _seed_task(database)
    repo = SqliteApprovalRepository(database)
    repo.add(_pending())
    repo.resolve(_pending().resolve(ApprovalStatus.APPROVED, decided_at=TS2, reason="ok"))
    fetched = repo.get(ApprovalId("AP-1"))
    assert fetched.status is ApprovalStatus.APPROVED
    assert fetched.decided_at == TS2
    assert len(repo.list_by_task(TaskId("TASK-1"))) == 1


def test_approval_double_resolve_rejected(database: Database) -> None:
    _seed_task(database)
    repo = SqliteApprovalRepository(database)
    repo.add(_pending())
    resolved = _pending().resolve(ApprovalStatus.APPROVED, decided_at=TS2)
    repo.resolve(resolved)
    with pytest.raises(ApprovalAlreadyResolved):
        repo.resolve(_pending().resolve(ApprovalStatus.REJECTED, decided_at=TS2))


def test_approval_resolve_missing(database: Database) -> None:
    _seed_task(database)
    repo = SqliteApprovalRepository(database)
    with pytest.raises(RecordNotFound):
        repo.resolve(_pending().resolve(ApprovalStatus.APPROVED, decided_at=TS2))
