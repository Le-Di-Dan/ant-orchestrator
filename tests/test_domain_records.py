"""Unit tests for domain records and the Approval lifecycle (CP2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    MemoryType,
    PheromoneType,
)
from ant_orchestrator.core.domain.errors import (
    ApprovalAlreadyResolved,
    InvariantViolation,
)
from ant_orchestrator.core.domain.records import (
    Approval,
    EnergyUsage,
    HandoffRecord,
    MemoryRecord,
    PheromoneRecord,
    WorkflowCheckpoint,
)
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    CheckpointId,
    EnergyUsageId,
    HandoffId,
    MemoryId,
    PheromoneId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)

TS = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))
TS2 = UtcTimestamp(datetime(2026, 6, 22, 1, tzinfo=UTC))


def test_energy_usage_requires_a_link() -> None:
    with pytest.raises(InvariantViolation):
        EnergyUsage(
            id=EnergyUsageId("E-1"),
            tokens_in=TokenCount(1),
            tokens_out=TokenCount(1),
            created_at=TS,
        )


def test_energy_usage_accepts_task_only() -> None:
    usage = EnergyUsage(
        id=EnergyUsageId("E-1"),
        tokens_in=TokenCount(10),
        tokens_out=TokenCount(5),
        created_at=TS,
        task_id=TaskId("TASK-1"),
    )
    assert usage.worker_run_id is None


def test_energy_usage_accepts_worker_run_only() -> None:
    usage = EnergyUsage(
        id=EnergyUsageId("E-1"),
        tokens_in=TokenCount(0),
        tokens_out=TokenCount(0),
        created_at=TS,
        worker_run_id=WorkerRunId("RUN-1"),
    )
    assert usage.task_id is None


def test_checkpoint_rejects_bad_version() -> None:
    with pytest.raises(InvariantViolation):
        WorkflowCheckpoint(
            id=CheckpointId("CK-1"),
            task_id=TaskId("TASK-1"),
            payload_version=0,
            payload={},
            created_at=TS,
        )


def _pending_approval() -> Approval:
    return Approval(
        id=ApprovalId("AP-1"),
        task_id=TaskId("TASK-1"),
        status=ApprovalStatus.PENDING,
        requested_at=TS,
    )


def test_approval_resolve_returns_new_instance() -> None:
    pending = _pending_approval()
    resolved = pending.resolve(ApprovalStatus.APPROVED, decided_at=TS2, reason="ok")
    assert resolved is not pending
    assert resolved.status is ApprovalStatus.APPROVED
    assert resolved.decided_at == TS2
    assert resolved.reason == "ok"
    assert pending.status is ApprovalStatus.PENDING


def test_approval_double_resolve_raises() -> None:
    resolved = _pending_approval().resolve(ApprovalStatus.REJECTED, decided_at=TS2)
    with pytest.raises(ApprovalAlreadyResolved):
        resolved.resolve(ApprovalStatus.APPROVED, decided_at=TS2)


def test_approval_resolve_with_pending_is_invalid() -> None:
    with pytest.raises(InvariantViolation):
        _pending_approval().resolve(ApprovalStatus.PENDING, decided_at=TS2)


def test_approval_pending_with_decided_at_is_invalid() -> None:
    with pytest.raises(InvariantViolation):
        Approval(
            id=ApprovalId("AP-1"),
            task_id=TaskId("TASK-1"),
            status=ApprovalStatus.PENDING,
            requested_at=TS,
            decided_at=TS2,
        )


def test_approval_resolved_without_decided_at_is_invalid() -> None:
    with pytest.raises(InvariantViolation):
        Approval(
            id=ApprovalId("AP-1"),
            task_id=TaskId("TASK-1"),
            status=ApprovalStatus.APPROVED,
            requested_at=TS,
        )


def test_memory_deprecate_returns_new_instance() -> None:
    memory = MemoryRecord(
        id=MemoryId("MEM-1"),
        type=MemoryType.PROJECT_FACT,
        title="t",
        summary="s",
        created_at=TS,
    )
    deprecated = memory.deprecate()
    assert deprecated.deprecated is True
    assert memory.deprecated is False


def test_handoff_requires_summary() -> None:
    with pytest.raises(InvariantViolation):
        HandoffRecord(id=HandoffId("H-1"), task_id=TaskId("TASK-1"), summary="", created_at=TS)


def test_pheromone_requires_summary() -> None:
    with pytest.raises(InvariantViolation):
        PheromoneRecord(
            id=PheromoneId("P-1"),
            type=PheromoneType.RISK_SIGNAL,
            summary="",
            created_at=TS,
        )
