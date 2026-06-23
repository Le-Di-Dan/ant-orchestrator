"""Round-trip tests for evidence/handoff/pheromone/memory repositories (CP6)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.core.domain.entities import Task, WorkerRun
from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    PheromoneType,
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.core.domain.records import (
    ExecutionEvidence,
    HandoffRecord,
    MemoryRecord,
    PheromoneRecord,
)
from ant_orchestrator.core.domain.value_objects import (
    EvidenceId,
    HandoffId,
    MemoryId,
    PheromoneId,
    TaskId,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.evidence import SqliteExecutionEvidenceRepository
from ant_orchestrator.persistence.repositories.handoff import SqliteHandoffRepository
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.repositories.pheromone import SqlitePheromoneRepository
from ant_orchestrator.persistence.repositories.task import SqliteTaskRepository
from ant_orchestrator.persistence.repositories.worker_run import SqliteWorkerRunRepository

TS = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))


def _seed_task_and_run(database: Database) -> None:
    SqliteTaskRepository(database).add(
        Task(
            id=TaskId("TASK-1"),
            title="demo",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=TS,
            updated_at=TS,
        )
    )
    SqliteWorkerRunRepository(database).add(
        WorkerRun(
            id=WorkerRunId("RUN-1"),
            task_id=TaskId("TASK-1"),
            status=WorkerRunStatus.RUNNING,
            created_at=TS,
        )
    )


def test_evidence_round_trip(database: Database) -> None:
    _seed_task_and_run(database)
    repo = SqliteExecutionEvidenceRepository(database)
    repo.append(
        ExecutionEvidence(
            id=EvidenceId("EV-1"),
            worker_run_id=WorkerRunId("RUN-1"),
            created_at=TS,
            files_read=("a.py", "b.py"),
            files_changed=("a.py",),
            commands=("pytest",),
            result="ok",
        )
    )
    fetched = repo.get(EvidenceId("EV-1"))
    assert fetched.files_read == ("a.py", "b.py")
    assert fetched.commands == ("pytest",)
    assert len(repo.list_by_worker_run(WorkerRunId("RUN-1"))) == 1


def test_handoff_round_trip(database: Database) -> None:
    SqliteTaskRepository(database).add(
        Task(
            id=TaskId("TASK-1"),
            title="demo",
            status=TaskStatus.CREATED,
            source=TaskSource.HUMAN,
            priority=TaskPriority.NORMAL,
            created_at=TS,
            updated_at=TS,
        )
    )
    repo = SqliteHandoffRepository(database)
    repo.append(
        HandoffRecord(
            id=HandoffId("H-1"),
            task_id=TaskId("TASK-1"),
            summary="done",
            created_at=TS,
            next_steps="ship",
        )
    )
    fetched = repo.get(HandoffId("H-1"))
    assert fetched.summary == "done"
    assert fetched.next_steps == "ship"
    assert fetched.what_changed is None
    assert len(repo.list_by_task(TaskId("TASK-1"))) == 1


def test_pheromone_round_trip(database: Database) -> None:
    repo = SqlitePheromoneRepository(database)
    repo.append(
        PheromoneRecord(
            id=PheromoneId("P-1"),
            type=PheromoneType.TEST_FAILURE,
            summary="auth fails",
            created_at=TS,
            files=("tests/test_auth.py",),
            expires_at=TS,
            confidence=ConfidenceLevel.MEDIUM,
        )
    )
    fetched = repo.get(PheromoneId("P-1"))
    assert fetched.type is PheromoneType.TEST_FAILURE
    assert fetched.files == ("tests/test_auth.py",)
    assert fetched.expires_at == TS
    assert fetched.confidence is ConfidenceLevel.MEDIUM


def test_memory_round_trip_and_deprecate(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    record = MemoryRecord(
        id=MemoryId("MEM-1"),
        type=MemoryType.TECHNICAL_DECISION,
        title="python first",
        summary="core uses python",
        created_at=TS,
        confidence=ConfidenceLevel.HIGH,
        tags=("python", "foundation"),
    )
    repo.append(record)
    fetched = repo.get(MemoryId("MEM-1"))
    assert fetched.tags == ("python", "foundation")
    assert fetched.deprecated is False
    repo.deprecate(record)
    assert repo.get(MemoryId("MEM-1")).deprecated is True
    assert len(repo.list_by_type(MemoryType.TECHNICAL_DECISION)) == 1


def test_memory_deprecate_missing(database: Database) -> None:
    repo = SqliteMemoryRepository(database)
    missing = MemoryRecord(
        id=MemoryId("MEM-X"),
        type=MemoryType.RISK_NOTE,
        title="t",
        summary="s",
        created_at=TS,
    )
    with pytest.raises(RecordNotFound):
        repo.deprecate(missing)
