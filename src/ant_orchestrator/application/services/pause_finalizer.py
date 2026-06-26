"""PauseFinalizer — persist a pending approval *after* a durable checkpoint.

PHASE_4_PLAN C.5: the approval is created only once a real interrupt checkpoint
exists, in a single unit of work that also moves the run to AWAITING_APPROVAL and the
task to WAITING_FOR_APPROVAL and appends the transitions. Replaying the finalizer is
idempotent: the ``UNIQUE(gate_instance_id)`` approval already exists, so it returns
without creating a second approval or duplicating transitions.
"""

from __future__ import annotations

from ant_orchestrator.application.errors import CheckpointRecoveryError
from ant_orchestrator.application.ports.workflow_runner import InterruptView
from ant_orchestrator.application.services.workflow_support import (
    UnitOfWorkFactory,
    append_transition,
    pause_operation_id,
)
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    GateType,
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.records import Approval
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    GateInstanceId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.unit_of_work import UnitOfWorkRepositories


class PauseFinalizer:
    """Finalizes a paused approval gate within one transaction (PHASE_4_PLAN C.5)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    def finalize(
        self, run_id: WorkflowRunId, interrupt: InterruptView, *, checkpoint_id: str | None
    ) -> str:
        """Create the PENDING approval (idempotent) and return its approval id."""
        gid_value = interrupt.gate_instance_id
        if gid_value is None or checkpoint_id is None:
            raise CheckpointRecoveryError("pause requires a gate-instance id and checkpoint id")
        with self._uow_factory() as uow:
            existing = uow.approvals.find_by_gate_instance(GateInstanceId(gid_value))
            if existing is not None:
                return existing.id.value
            return self._finalize_fresh(uow, run_id, interrupt, gid_value, checkpoint_id)

    def _finalize_fresh(
        self,
        uow: UnitOfWorkRepositories,
        run_id: WorkflowRunId,
        interrupt: InterruptView,
        gid_value: str,
        checkpoint_id: str,
    ) -> str:
        now = self._clock.now()
        run = uow.workflow_runs.get(run_id)
        task = uow.tasks.get(run.task_id)
        payload = interrupt.payload
        _seq = payload.get("approval_gate_sequence")
        approval = Approval(
            id=ApprovalId(self._ids.new_id()),
            task_id=run.task_id,
            status=ApprovalStatus.PENDING,
            requested_at=now,
            workflow_run_id=run.id,
            gate_type=GateType.parse(str(payload["gate_type"])),
            gate_instance_id=GateInstanceId(gid_value),
            approval_gate_sequence=int(_seq) if isinstance(_seq, int) else 0,
            langgraph_checkpoint_id=checkpoint_id,
            langgraph_interrupt_id=interrupt.langgraph_interrupt_id,
            request_payload=dict(payload),
        )
        uow.approvals.add(approval)
        uow.workflow_runs.update(
            run.with_checkpoint_observed(checkpoint_id, now=now).with_status(
                WorkflowRunStatus.AWAITING_APPROVAL, now=now
            )
        )
        uow.tasks.update(task.with_status(TaskStatus.WAITING_FOR_APPROVAL, now=now))
        self._append_pause_transitions(uow, run.id, gid_value, now=now)
        return approval.id.value

    def _append_pause_transitions(
        self,
        uow: UnitOfWorkRepositories,
        run_id: WorkflowRunId,
        gid_value: str,
        *,
        now: UtcTimestamp,
    ) -> None:
        op_id = pause_operation_id(gid_value)
        trigger = TransitionTrigger.AWAIT_APPROVAL
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.RUN,
            to_status=WorkflowRunStatus.AWAITING_APPROVAL.value,
            trigger=trigger,
            operation_id=op_id,
            from_status=WorkflowRunStatus.RUNNING.value,
        )
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.TASK,
            to_status=TaskStatus.WAITING_FOR_APPROVAL.value,
            trigger=trigger,
            operation_id=op_id,
        )
        append_transition(
            uow.transitions,
            ids=self._ids,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.APPROVAL,
            to_status=ApprovalStatus.PENDING.value,
            trigger=trigger,
            operation_id=op_id,
        )
