"""Invariant tests for Phase 4 workflow entities/records (CP1)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ExecutionAttemptStatus,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.errors import (
    ApprovalAlreadyResolved,
    InvariantViolation,
)
from tests.support.workflow_factories import (
    TS,
    make_attempt,
    make_pending_approval,
    make_resume,
    make_run,
)


def test_workflow_run_requires_thread_id() -> None:
    with pytest.raises(InvariantViolation):
        replace(make_run(), thread_id="")


def test_workflow_run_status_helpers() -> None:
    assert WorkflowRunStatus.RUNNING.is_active
    assert WorkflowRunStatus.AWAITING_APPROVAL.is_active
    assert not WorkflowRunStatus.COMPLETED.is_active
    assert WorkflowRunStatus.CANCELLED.is_terminal


def test_workflow_run_cancel_request_is_idempotent() -> None:
    run = make_run()
    once = run.with_cancel_requested(now=TS)
    assert once.cancel_requested_at == TS
    twice = once.with_cancel_requested(now=TS)
    assert twice is once  # already flagged: no new timestamp


def test_workflow_run_observe_checkpoint() -> None:
    run = make_run().with_checkpoint_observed("ckpt-9", now=TS)
    assert run.checkpoint_ever_observed
    assert run.last_observed_checkpoint_id == "ckpt-9"


def test_execution_attempt_rejects_zero_attempt_no() -> None:
    with pytest.raises(InvariantViolation):
        make_attempt(attempt_no=0)


def test_execution_attempt_status_helpers() -> None:
    assert ExecutionAttemptStatus.PLANNED.is_active
    assert ExecutionAttemptStatus.STARTED.is_active
    assert ExecutionAttemptStatus.INDETERMINATE.is_terminal
    assert not ExecutionAttemptStatus.INDETERMINATE.is_active


def test_resume_operation_rejects_pending_decision() -> None:
    with pytest.raises(InvariantViolation):
        make_resume(decision=ApprovalStatus.PENDING)


def test_approval_resolve_to_cancelled_bumps_version() -> None:
    approval = make_pending_approval()
    cancelled = approval.resolve(ApprovalStatus.CANCELLED, decided_at=TS)
    assert cancelled.status is ApprovalStatus.CANCELLED
    assert cancelled.approval_row_version == approval.approval_row_version + 1


def test_approval_resolve_once() -> None:
    approval = make_pending_approval().resolve(ApprovalStatus.APPROVED, decided_at=TS)
    with pytest.raises(ApprovalAlreadyResolved):
        approval.resolve(ApprovalStatus.REJECTED, decided_at=TS)


def test_approval_rejects_pending_decision() -> None:
    with pytest.raises(InvariantViolation):
        make_pending_approval().resolve(ApprovalStatus.PENDING, decided_at=TS)
