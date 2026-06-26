"""Repository + invariant (unique/partial-unique/CAS) tests for Phase 4 tables (CP1)."""

from __future__ import annotations

import sqlite3

import pytest

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ExecutionAttemptStatus,
    TransitionSubject,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    ExecutionAttemptId,
    GateInstanceId,
    TaskId,
    WorkflowRunId,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.support.workflow_factories import (
    TS,
    make_attempt,
    make_pending_approval,
    make_resume,
    make_run,
    make_task,
    make_transition,
)


def _seed_run(database: Database) -> None:
    with SqliteUnitOfWork(database) as repos:
        repos.tasks.add(make_task())
        repos.workflow_runs.add(make_run())


def _seed_approval(database: Database, approval_id: str = "A1", gate: str = "gate-1") -> None:
    with SqliteUnitOfWork(database) as repos:
        repos.approvals.add(make_pending_approval(approval_id, gate_instance_id=gate))


# --- WorkflowRun -------------------------------------------------------------


def test_workflow_run_roundtrip_and_find_active(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        assert repos.workflow_runs.get(WorkflowRunId("R1")).task_id == TaskId("T1")
        active = repos.workflow_runs.find_active_by_task(TaskId("T1"))
        assert active is not None and active.id == WorkflowRunId("R1")


def test_single_active_run_per_task_is_blocked(database: Database) -> None:
    _seed_run(database)
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.workflow_runs.add(make_run(run_id="R2"))


def test_terminal_run_frees_active_slot(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        run = repos.workflow_runs.get(WorkflowRunId("R1"))
        done = run.with_status(WorkflowRunStatus.COMPLETED, now=TS)
        assert repos.workflow_runs.compare_and_set_status(done, expected=WorkflowRunStatus.RUNNING)
    with SqliteUnitOfWork(database) as repos:
        repos.workflow_runs.add(make_run(run_id="R2"))  # no active conflict now
        assert repos.workflow_runs.find_active_by_task(TaskId("T1")) is not None


def test_workflow_run_cas_rejects_stale_expected(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        run = repos.workflow_runs.get(WorkflowRunId("R1"))
        cancelled = run.with_status(WorkflowRunStatus.CANCELLED, now=TS)
        # Stored status is RUNNING, but we guard on AWAITING_APPROVAL -> CAS loses.
        ok = repos.workflow_runs.compare_and_set_status(
            cancelled, expected=WorkflowRunStatus.AWAITING_APPROVAL
        )
        assert ok is False
        assert repos.workflow_runs.get(WorkflowRunId("R1")).status is WorkflowRunStatus.RUNNING


# --- StatusTransition --------------------------------------------------------


def test_transition_operation_id_is_unique_per_subject(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        repos.transitions.append(
            make_transition("X1", subject=TransitionSubject.RUN, operation_id="op-shared")
        )
        # Same (operation_id, subject) again -> rejected.
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.transitions.append(
                make_transition("X2", subject=TransitionSubject.RUN, operation_id="op-shared")
            )


def test_transition_same_operation_different_subject_allowed(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        repos.transitions.append(
            make_transition("X1", subject=TransitionSubject.RUN, operation_id="op-shared")
        )
        repos.transitions.append(
            make_transition("X2", subject=TransitionSubject.TASK, operation_id="op-shared")
        )
        assert len(repos.transitions.list_by_run(WorkflowRunId("R1"))) == 2


# --- ExecutionAttempt --------------------------------------------------------


def test_only_one_active_attempt_per_action(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        repos.execution_attempts.add(make_attempt("EA1", attempt_no=1))
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.execution_attempts.add(make_attempt("EA2", attempt_no=2))


def test_indeterminate_frees_active_slot_for_new_attempt(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        repos.execution_attempts.add(make_attempt("EA1", attempt_no=1))
        stuck = repos.execution_attempts.get(ExecutionAttemptId("EA1"))
        repos.execution_attempts.update(stuck.with_status(ExecutionAttemptStatus.INDETERMINATE))
        repos.execution_attempts.add(make_attempt("EA2", attempt_no=2))  # allowed now
        assert repos.execution_attempts.find_active(WorkflowRunId("R1"), "act-1").id.value == "EA2"


def test_attempt_no_unique_per_action(database: Database) -> None:
    _seed_run(database)
    with SqliteUnitOfWork(database) as repos:
        repos.execution_attempts.add(
            make_attempt("EA1", attempt_no=1, status=ExecutionAttemptStatus.SUCCEEDED)
        )
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.execution_attempts.add(
                make_attempt("EA2", attempt_no=1, status=ExecutionAttemptStatus.FAILED)
            )


# --- ResumeOperation ---------------------------------------------------------


def test_resume_operation_unique_per_approval(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database)
    with SqliteUnitOfWork(database) as repos:
        repos.resume_operations.add(make_resume("RO1"))
        found = repos.resume_operations.find_by_approval(ApprovalId("A1"))
        assert found is not None and found.id.value == "RO1"
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.resume_operations.add(make_resume("RO2", interrupt_id="int-2"))


def test_resume_operation_unique_per_run_and_interrupt(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database, "A1", gate="gate-1")  # pending approval on R1
    with SqliteUnitOfWork(database) as repos:
        # A second, already-resolved approval on the same run is allowed (the
        # pending-per-run index only blocks a second *pending* one).
        resolved = make_pending_approval("A2", gate_instance_id="gate-2").resolve(
            ApprovalStatus.APPROVED, decided_at=TS
        )
        repos.approvals.add(resolved)
    with SqliteUnitOfWork(database) as repos:
        repos.resume_operations.add(make_resume("RO1", approval_id="A1", interrupt_id="int-1"))
    # Same (run, interrupt) under a different approval -> defense-in-depth rejects it.
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.resume_operations.add(make_resume("RO2", approval_id="A2", interrupt_id="int-1"))


# --- Approval (v2) -----------------------------------------------------------


def test_approval_gate_instance_is_unique(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database, "A1", gate="gate-1")
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.approvals.add(make_pending_approval("A2", gate_instance_id="gate-1"))


def test_only_one_pending_approval_per_run(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database, "A1", gate="gate-1")
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.approvals.add(make_pending_approval("A2", gate_instance_id="gate-2"))


def test_approval_lookups(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database, "A1", gate="gate-1")
    with SqliteUnitOfWork(database) as repos:
        by_gate = repos.approvals.find_by_gate_instance(GateInstanceId("gate-1"))
        assert by_gate is not None and by_gate.id == ApprovalId("A1")
        pending = repos.approvals.find_pending_by_run(WorkflowRunId("R1"))
        assert pending is not None and pending.status is ApprovalStatus.PENDING


def test_approval_resolve_with_version_cas(database: Database) -> None:
    _seed_run(database)
    _seed_approval(database, "A1", gate="gate-1")
    with SqliteUnitOfWork(database) as repos:
        approval = repos.approvals.get(ApprovalId("A1"))
        resolved = approval.resolve(ApprovalStatus.APPROVED, decided_at=TS)
        assert repos.approvals.resolve_with_version(resolved, expected_version=1) is True
        # A stale writer that still believes the row is at version 1 now loses.
        stale = approval.resolve(ApprovalStatus.REJECTED, decided_at=TS)
        assert repos.approvals.resolve_with_version(stale, expected_version=1) is False
        assert repos.approvals.get(ApprovalId("A1")).status is ApprovalStatus.APPROVED
