"""Builders for Phase 4 workflow entities/records (test-only)."""

from __future__ import annotations

from datetime import UTC, datetime

from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ExecutionAttemptStatus,
    GateType,
    ResumeOperationStatus,
    TaskPriority,
    TaskSource,
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.records import Approval
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    ExecutionAttemptId,
    GateInstanceId,
    ResumeOperationId,
    TaskId,
    TransitionId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import (
    ExecutionAttempt,
    ResumeOperation,
    StatusTransition,
    WorkflowRun,
)

TS = UtcTimestamp(datetime(2026, 6, 26, tzinfo=UTC))


def make_task(task_id: str = "T1", status: TaskStatus = TaskStatus.CREATED) -> Task:
    return Task(
        id=TaskId(task_id),
        title="demo",
        status=status,
        source=TaskSource.HUMAN,
        priority=TaskPriority.NORMAL,
        created_at=TS,
        updated_at=TS,
    )


def make_run(
    run_id: str = "R1",
    task_id: str = "T1",
    status: WorkflowRunStatus = WorkflowRunStatus.RUNNING,
) -> WorkflowRun:
    return WorkflowRun(
        id=WorkflowRunId(run_id),
        task_id=TaskId(task_id),
        thread_id=f"wf:{run_id}",
        status=status,
        workflow_definition_version=1,
        initial_invoke_operation_id=f"op-invoke-{run_id}",
        created_at=TS,
        updated_at=TS,
    )


def make_transition(
    transition_id: str = "X1",
    run_id: str = "R1",
    *,
    subject: TransitionSubject = TransitionSubject.RUN,
    to_status: str = "running",
    trigger: TransitionTrigger = TransitionTrigger.RUN_CREATED,
    operation_id: str = "op-1",
) -> StatusTransition:
    return StatusTransition(
        id=TransitionId(transition_id),
        workflow_run_id=WorkflowRunId(run_id),
        subject=subject,
        to_status=to_status,
        trigger=trigger,
        operation_id=operation_id,
        created_at=TS,
    )


def make_attempt(
    attempt_id: str = "EA1",
    run_id: str = "R1",
    *,
    logical_action_id: str = "act-1",
    attempt_no: int = 1,
    status: ExecutionAttemptStatus = ExecutionAttemptStatus.STARTED,
    owner_token: str | None = "owner-1",
) -> ExecutionAttempt:
    return ExecutionAttempt(
        id=ExecutionAttemptId(attempt_id),
        workflow_run_id=WorkflowRunId(run_id),
        logical_action_id=logical_action_id,
        attempt_no=attempt_no,
        status=status,
        created_at=TS,
        owner_token=owner_token,
    )


def make_resume(
    operation_id: str = "RO1",
    run_id: str = "R1",
    approval_id: str = "A1",
    *,
    decision: ApprovalStatus = ApprovalStatus.APPROVED,
    status: ResumeOperationStatus = ResumeOperationStatus.OWNED,
    interrupt_id: str | None = "int-1",
) -> ResumeOperation:
    return ResumeOperation(
        id=ResumeOperationId(operation_id),
        workflow_run_id=WorkflowRunId(run_id),
        approval_id=ApprovalId(approval_id),
        decision=decision,
        status=status,
        created_at=TS,
        langgraph_interrupt_id=interrupt_id,
        owner_token="owner-1",
    )


def make_pending_approval(
    approval_id: str = "A1",
    task_id: str = "T1",
    run_id: str = "R1",
    *,
    gate_instance_id: str | None = "gate-1",
    gate_type: GateType = GateType.SIGNIFICANT_WRITE,
    sequence: int = 0,
) -> Approval:
    return Approval(
        id=ApprovalId(approval_id),
        task_id=TaskId(task_id),
        status=ApprovalStatus.PENDING,
        requested_at=TS,
        workflow_run_id=WorkflowRunId(run_id),
        gate_type=gate_type,
        gate_instance_id=GateInstanceId(gate_instance_id) if gate_instance_id else None,
        approval_gate_sequence=sequence,
    )
