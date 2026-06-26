"""Phase 4 workflow-execution entities and records (PHASE_4_PLAN B.2/C.9).

These model the *execution* layer that sits beside the business ``Task``:

* ``WorkflowRun``     — one execution of the graph for a task (durable cursor owner).
* ``StatusTransition``— append-only audit row carrying a stable ``operation_id``.
* ``ExecutionAttempt``— one attempt of a logical action (no exactly-once claim).
* ``ResumeOperation`` — a concurrent-resume owner lease around a paused approval.

All are immutable; lifecycle changes return new instances (consistent with D28).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ExecutionAttemptStatus,
    ResumeOperationStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    ExecutionAttemptId,
    ResumeOperationId,
    TaskId,
    TransitionId,
    UtcTimestamp,
    WorkflowRunId,
)

_RESUME_DECISIONS = (
    ApprovalStatus.APPROVED,
    ApprovalStatus.REJECTED,
    ApprovalStatus.CANCELLED,
)


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    """One execution of the workflow graph for a Task (PHASE_4_PLAN C.2/C.5c).

    ``thread_id`` is the deterministic LangGraph durable cursor. The three crash-
    distinction fields (``initial_invoke_operation_id``, ``checkpoint_ever_observed``,
    ``last_observed_checkpoint_id``) let recovery tell "invoke never happened" apart
    from "checkpoint was lost" (fail-closed) without trusting an empty snapshot.
    """

    id: WorkflowRunId
    task_id: TaskId
    thread_id: str
    status: WorkflowRunStatus
    workflow_definition_version: int
    initial_invoke_operation_id: str
    created_at: UtcTimestamp
    updated_at: UtcTimestamp
    checkpoint_ever_observed: bool = False
    last_observed_checkpoint_id: str | None = None
    cancel_requested_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if not self.thread_id:
            raise InvariantViolation("WorkflowRun.thread_id must be non-empty")
        if not self.initial_invoke_operation_id:
            raise InvariantViolation("WorkflowRun.initial_invoke_operation_id must be non-empty")
        if self.workflow_definition_version < 1:
            raise InvariantViolation("WorkflowRun.workflow_definition_version must be >= 1")
        if self.updated_at.value < self.created_at.value:
            raise InvariantViolation("WorkflowRun.updated_at must not precede created_at")

    def with_status(self, status: WorkflowRunStatus, *, now: UtcTimestamp) -> WorkflowRun:
        """Return a copy with a new status and refreshed ``updated_at``."""
        return replace(self, status=status, updated_at=now)

    def with_checkpoint_observed(self, checkpoint_id: str, *, now: UtcTimestamp) -> WorkflowRun:
        """Return a copy recording that a durable checkpoint has been observed."""
        return replace(
            self,
            checkpoint_ever_observed=True,
            last_observed_checkpoint_id=checkpoint_id,
            updated_at=now,
        )

    def with_cancel_requested(self, *, now: UtcTimestamp) -> WorkflowRun:
        """Return a copy flagging a cancellation intent (idempotent timestamp)."""
        if self.cancel_requested_at is not None:
            return self
        return replace(self, cancel_requested_at=now, updated_at=now)


@dataclass(frozen=True, slots=True)
class StatusTransition:
    """An append-only record of one lifecycle transition (PHASE_4_PLAN C.13).

    ``operation_id`` is the idempotency key: replaying the same logical operation
    must not append a second row (enforced by a UNIQUE index in persistence).
    """

    id: TransitionId
    workflow_run_id: WorkflowRunId
    subject: TransitionSubject
    to_status: str
    trigger: TransitionTrigger
    operation_id: str
    created_at: UtcTimestamp
    from_status: str | None = None
    causation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.to_status:
            raise InvariantViolation("StatusTransition.to_status must be non-empty")
        if not self.operation_id:
            raise InvariantViolation("StatusTransition.operation_id must be non-empty")


@dataclass(frozen=True, slots=True)
class ExecutionAttempt:
    """A single attempt of a logical action (PHASE_4_PLAN C.9).

    Phase 4 makes *no* exactly-once claim for real side effects. A stuck STARTED
    attempt whose lease has expired is marked INDETERMINATE (never FAILED) and a new
    ``attempt_no`` is created; INDETERMINATE is terminal-for-the-attempt only.
    """

    id: ExecutionAttemptId
    workflow_run_id: WorkflowRunId
    logical_action_id: str
    attempt_no: int
    status: ExecutionAttemptStatus
    created_at: UtcTimestamp
    owner_token: str | None = None
    lease_expires_at: UtcTimestamp | None = None
    started_at: UtcTimestamp | None = None
    completed_at: UtcTimestamp | None = None
    outcome: str | None = None

    def __post_init__(self) -> None:
        if not self.logical_action_id:
            raise InvariantViolation("ExecutionAttempt.logical_action_id must be non-empty")
        if self.attempt_no < 1:
            raise InvariantViolation("ExecutionAttempt.attempt_no must be >= 1")

    def with_status(
        self,
        status: ExecutionAttemptStatus,
        *,
        completed_at: UtcTimestamp | None = None,
        outcome: str | None = None,
    ) -> ExecutionAttempt:
        """Return a copy with a new status and optional completion metadata."""
        return replace(
            self,
            status=status,
            completed_at=completed_at if completed_at is not None else self.completed_at,
            outcome=outcome if outcome is not None else self.outcome,
        )


@dataclass(frozen=True, slots=True)
class ResumeOperation:
    """A concurrent-resume owner lease around a paused approval (PHASE_4_PLAN C.5b).

    Exactly one owner (``owner_token`` won via CAS) may invoke the graph resume; the
    ``decision`` is the terminal ApprovalStatus to apply (approved/rejected/cancelled).
    """

    id: ResumeOperationId
    workflow_run_id: WorkflowRunId
    approval_id: ApprovalId
    decision: ApprovalStatus
    status: ResumeOperationStatus
    created_at: UtcTimestamp
    langgraph_checkpoint_id: str | None = None
    langgraph_interrupt_id: str | None = None
    owner_token: str | None = None
    lease_expires_at: UtcTimestamp | None = None
    completed_at: UtcTimestamp | None = None

    def __post_init__(self) -> None:
        if self.decision not in _RESUME_DECISIONS:
            raise InvariantViolation(f"ResumeOperation.decision invalid: {self.decision}")

    def with_status(
        self,
        status: ResumeOperationStatus,
        *,
        completed_at: UtcTimestamp | None = None,
    ) -> ResumeOperation:
        """Return a copy with a new status and optional completion timestamp."""
        return replace(
            self,
            status=status,
            completed_at=completed_at if completed_at is not None else self.completed_at,
        )
