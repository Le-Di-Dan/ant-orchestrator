"""CP4 — ResolveApproval integration tests.

Covers approve/reject happy paths, idempotent terminal retry, PauseFinalizer
fail-closed, concurrent-approve guard, UoW atomic conflict, and decision conflict.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.application.errors import ApprovalStateConflict
from ant_orchestrator.application.ports.workflow_runner import InterruptView
from ant_orchestrator.application.services.pause_finalizer import PauseFinalizer
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ResumeOperationStatus,
    TaskStatus,
)
from ant_orchestrator.core.domain.value_objects import ApprovalId, TaskId, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_task,
    build_services,
    make_interrupt_runner,
    uow_factory,
)
from tests.support.workflow_factories import make_resume
from tests.support.workflow_runtime import CountingWorker

# ---------------------------------------------------------------------------
# Approve path
# ---------------------------------------------------------------------------


def test_approve_resumes_graph_and_finalizes_completed(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """APPROVE resumes the graph → approved_continuation=EXECUTE → worker=1 → COMPLETED."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")  # → AWAITING_APPROVAL; worker not called before gate
    outcome = resolve_svc.approve("T1")

    assert outcome.status == TaskStatus.COMPLETED.value
    assert worker.calls == 1  # called exactly once during resumed execute_stub

    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
    assert task.status == TaskStatus.COMPLETED
    assert active_run is None


def test_approve_settles_resume_operation_to_completed(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CompletionFinalizer settles the ResumeOperation to COMPLETED after approve."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    pause_outcome = run_svc.execute("T1")
    assert pause_outcome.approval_id is not None
    resolve_svc.approve("T1")

    with SqliteUnitOfWork(database) as uow:
        op = uow.resume_operations.find_by_approval(ApprovalId(pause_outcome.approval_id))
    assert op is not None
    assert op.status == ResumeOperationStatus.COMPLETED


# ---------------------------------------------------------------------------
# Reject path
# ---------------------------------------------------------------------------


def test_reject_routes_graph_to_rejected_terminal(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """REJECT resumes the graph → routes to rejected terminal → 0 worker calls."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")
    outcome = resolve_svc.reject("T1", reason="not safe")

    assert outcome.status == TaskStatus.REJECTED.value
    assert worker.calls == 0

    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
    assert task.status == TaskStatus.REJECTED


def test_reject_resolves_approval_exactly_once(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """The Approval is resolved to REJECTED exactly once (not again by CompletionFinalizer)."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")
    resolve_svc.reject("T1")

    with SqliteUnitOfWork(database) as uow:
        all_approvals = uow.approvals.list_by_task(TaskId("T1"))
    assert len(all_approvals) == 1
    assert all_approvals[0].status == ApprovalStatus.REJECTED


# ---------------------------------------------------------------------------
# Idempotency and conflict
# ---------------------------------------------------------------------------


def test_approve_after_completed_is_idempotent(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Second approve after COMPLETED returns COMPLETED idempotently (MICRO #2).

    The first approve drives the graph to completion; the second finds a terminal task
    and returns the terminal status without re-invoking the worker.
    """
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")
    first = resolve_svc.approve("T1")
    assert first.status == TaskStatus.COMPLETED.value

    second = resolve_svc.approve("T1")
    assert second.status == TaskStatus.COMPLETED.value
    assert worker.calls == 1  # worker not re-invoked by the idempotent second call


def test_approve_after_reject_raises_conflict(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """A *different* decision after a REJECTED terminal is a conflict (CP8 correction)."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")
    assert resolve_svc.reject("T1").status == TaskStatus.REJECTED.value

    # The persisted decision (REJECTED) is checked before any terminal return.
    with pytest.raises(ApprovalStateConflict):
        resolve_svc.approve("T1")
    assert worker.calls == 0


# ---------------------------------------------------------------------------
# PauseFinalizer fail-closed on missing interrupt fields (CP4 evidence §3)
# ---------------------------------------------------------------------------


def test_pause_finalizer_requires_gate_instance_id(
    database: Database,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """PauseFinalizer raises CheckpointRecoveryError when interrupt has no gate_instance_id."""
    from ant_orchestrator.application.errors import CheckpointRecoveryError

    pause = PauseFinalizer(uow_factory(database), clock=clock, ids=id_gen)
    interrupt = InterruptView(
        langgraph_interrupt_id="int-1",
        gate_instance_id=None,
        payload={},
    )
    with pytest.raises(CheckpointRecoveryError):
        pause.finalize(WorkflowRunId("R-bad"), interrupt, checkpoint_id="ck-1")


def test_pause_finalizer_requires_checkpoint_id(
    database: Database,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """PauseFinalizer raises CheckpointRecoveryError when checkpoint_id is None."""
    from ant_orchestrator.application.errors import CheckpointRecoveryError

    pause = PauseFinalizer(uow_factory(database), clock=clock, ids=id_gen)
    interrupt = InterruptView(
        langgraph_interrupt_id="int-1",
        gate_instance_id="gate-99",
        payload={},
    )
    with pytest.raises(CheckpointRecoveryError):
        pause.finalize(WorkflowRunId("R-bad"), interrupt, checkpoint_id=None)


# ---------------------------------------------------------------------------
# Concurrent approve guard — only one owner (CP4 evidence §10)
# ---------------------------------------------------------------------------


def test_concurrent_approve_second_call_backs_off(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Concurrent approve: pre-existing OWNED ResumeOperation prevents second owner.

    Simulates process A holding the lease (OWNED op pre-inserted) while process B
    calls approve. Process B must NOT resume the graph (worker stays at 0) and must
    not become an owner — it returns the current stable task state.
    """
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    pause_outcome = run_svc.execute("T1")
    assert pause_outcome.approval_id is not None

    # Simulate process A having already acquired the lease (OWNED).
    with SqliteUnitOfWork(database) as uow:
        approval = uow.approvals.find_pending_by_run(
            uow.workflow_runs.find_active_by_task(TaskId("T1")).id
        )
        pre_op = make_resume(
            "RO-proc-a",
            run_id=uow.workflow_runs.find_active_by_task(TaskId("T1")).id.value,
            approval_id=approval.id.value,
            decision=ApprovalStatus.APPROVED,
            status=ResumeOperationStatus.OWNED,
            interrupt_id=approval.langgraph_interrupt_id,
        )
        uow.resume_operations.add(pre_op)

    # Process B calls approve — should back off (not become owner, not resume).
    outcome = resolve_svc.approve("T1")

    assert worker.calls == 0
    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value


# ---------------------------------------------------------------------------
# UoW atomic rollback on version conflict (crash #4 — CP4 evidence §5)
# ---------------------------------------------------------------------------


def test_resolve_decision_conflict_leaves_no_new_resume_operation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Crash#4 UoW atomic: ApprovalStateConflict raised before mutations → no partial state.

    When a concurrent REJECT-decision owner already holds the lease, an APPROVE call
    raises ApprovalStateConflict inside the UoW before inserting its own ResumeOperation.
    The rollback guarantees no additional operation is persisted.
    """
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    pause_outcome = run_svc.execute("T1")
    assert pause_outcome.approval_id is not None

    # Pre-insert an OWNED REJECT operation — simulates process A about to reject.
    with SqliteUnitOfWork(database) as uow:
        approval = uow.approvals.get(ApprovalId(pause_outcome.approval_id))
        reject_op = make_resume(
            "RO-reject-owner",
            run_id=approval.workflow_run_id.value,
            approval_id=approval.id.value,
            decision=ApprovalStatus.REJECTED,
            status=ResumeOperationStatus.OWNED,
            interrupt_id=approval.langgraph_interrupt_id,
        )
        uow.resume_operations.add(reject_op)

    # Process B tries to APPROVE — conflicts with the existing REJECT owner.
    with pytest.raises(ApprovalStateConflict):
        resolve_svc.approve("T1")

    # Only the pre-inserted REJECT op exists; no new (APPROVE) op was created.
    with sqlite3.connect(str(database.path)) as conn:
        count = conn.execute("SELECT COUNT(*) FROM resume_operations").fetchone()[0]
    assert count == 1
    assert worker.calls == 0


# ---------------------------------------------------------------------------
# Idempotent retry: terminal task returns stable outcome (CP4 evidence §8)
# ---------------------------------------------------------------------------


def test_approve_terminal_task_returns_idempotent(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """ResumeOp COMPLETED → terminal idempotent: second approve returns COMPLETED, not raises."""
    worker = CountingWorker()
    runner = make_interrupt_runner(tmp_path, worker)
    run_svc, resolve_svc, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_svc.execute("T1")
    first = resolve_svc.approve("T1")
    assert first.status == TaskStatus.COMPLETED.value

    # Second call: task is already COMPLETED → idempotent return, no re-resume.
    second = resolve_svc.approve("T1")
    assert second.status == TaskStatus.COMPLETED.value
    assert worker.calls == 1  # worker invoked exactly once across both calls
