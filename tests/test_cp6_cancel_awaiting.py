"""CP6 — CancelTask AWAITING_APPROVAL + checkpoint recovery tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ResumeOperationStatus,
    TaskStatus,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import ApprovalId, TaskId, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_task,
    build_cancel_svc,
    build_services,
    make_interrupt_runner,
)
from tests.support.workflow_runtime import CountingWorker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run_to_awaiting(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
    task_id: str = "T1",
) -> tuple[str, str]:
    """Drive task to AWAITING_APPROVAL; return (run_id, approval_id)."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, task_id, clock=clock)
    outcome = run_svc.execute(task_id)
    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert outcome.approval_id is not None
    return outcome.run_id, outcome.approval_id


# ---------------------------------------------------------------------------
# AWAITING_APPROVAL cancellation
# ---------------------------------------------------------------------------


def test_awaiting_cancel_sets_task_run_cancelled(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Cancel on AWAITING task → CompletionFinalizer → Task + Run CANCELLED."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    run_svc.execute("T1")  # → AWAITING_APPROVAL

    outcome = cancel_svc.cancel("T1")

    assert outcome.status == TaskStatus.CANCELLED.value
    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
    assert task.status == TaskStatus.CANCELLED
    assert active_run is None


def test_awaiting_cancel_resolves_approval_cancelled_once(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Approval is resolved to CANCELLED exactly once after cancel."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    outcome_run = run_svc.execute("T1")
    approval_id = outcome_run.approval_id
    assert approval_id is not None

    cancel_svc.cancel("T1")

    with SqliteUnitOfWork(database) as uow:
        approval = uow.approvals.get(ApprovalId(approval_id))
    assert approval.status == ApprovalStatus.CANCELLED


def test_awaiting_cancel_creates_resume_operation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CancelTask acquires a ResumeOperation before resolving the Approval."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    outcome_run = run_svc.execute("T1")
    approval_id = outcome_run.approval_id
    assert approval_id is not None

    cancel_svc.cancel("T1")

    with SqliteUnitOfWork(database) as uow:
        approval = uow.approvals.get(ApprovalId(approval_id))
        resume_op = uow.resume_operations.find_by_approval(approval.id)
    assert resume_op is not None
    assert resume_op.decision == ApprovalStatus.CANCELLED
    assert resume_op.status == ResumeOperationStatus.COMPLETED


def test_awaiting_cancel_zero_worker_invocations(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Worker must not be invoked during AWAITING cancel (gate was not approved)."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    run_svc.execute("T1")  # no worker call (gate fires first)
    worker_calls_before_cancel = worker.calls

    cancel_svc.cancel("T1")

    assert worker.calls == worker_calls_before_cancel  # still 0


def test_awaiting_cancel_duplicate_reuses_resume_operation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Duplicate cancel on AWAITING task returns current status; no second ResumeOperation."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    run_svc.execute("T1")

    cancel_svc.cancel("T1")
    outcome2 = cancel_svc.cancel("T1")

    assert outcome2.status == TaskStatus.CANCELLED.value
    with sqlite3.connect(str(database.path)) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM resume_operations").fetchone()
    assert rows[0] == 1


def test_awaiting_approve_after_cancel_raises_conflict(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """After CANCELLED terminal, a different decision (approve) is a conflict (CP8)."""
    from ant_orchestrator.application.errors import ApprovalStateConflict

    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    run_svc.execute("T1")

    cancel_svc.cancel("T1")

    # Task is CANCELLED; the persisted decision is checked before any terminal return,
    # so a conflicting APPROVE fails closed instead of returning a misleading status.
    with pytest.raises(ApprovalStateConflict):
        resolve_svc.approve("T1")


def test_awaiting_cancel_approval_transition_recorded(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Cancel on AWAITING appends approval transition to CANCELLED."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    outcome_run = run_svc.execute("T1")
    run_id = outcome_run.run_id

    cancel_svc.cancel("T1")

    with sqlite3.connect(str(database.path)) as conn:
        rows = conn.execute(
            "SELECT to_status FROM status_transitions WHERE subject = 'approval' "
            "AND trigger = 'cancel' AND workflow_run_id = ?",
            (run_id,),
        ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "cancelled"


def test_awaiting_cancel_completion_finalizer_sets_cancelled(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CompletionFinalizer maps 'cancelled' final_outcome to CANCELLED terminal statuses."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    outcome_run = run_svc.execute("T1")
    run_id_vo = WorkflowRunId(outcome_run.run_id)

    cancel_svc.cancel("T1")

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.get(run_id_vo)
        task = uow.tasks.get(TaskId("T1"))
    assert run.status == WorkflowRunStatus.CANCELLED
    assert task.status == TaskStatus.CANCELLED


def test_awaiting_cancel_uow_rollback_leaves_no_partial_approval(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """If cancel UoW fails midway, Approval stays PENDING (no partial resolve)."""
    import unittest.mock as mock

    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)
    outcome_run = run_svc.execute("T1")
    approval_id = outcome_run.approval_id
    assert approval_id is not None

    # Make the resume_operations.add call fail so the UoW rolls back.
    with mock.patch(
        "ant_orchestrator.persistence.repositories.resume_operation.ResumeOperationRepository.add",
        side_effect=RuntimeError("simulated failure"),
    ):
        with pytest.raises(RuntimeError, match="simulated failure"):
            cancel_svc.cancel("T1")

    with SqliteUnitOfWork(database) as uow:
        approval = uow.approvals.get(ApprovalId(approval_id))
    assert approval.status == ApprovalStatus.PENDING
