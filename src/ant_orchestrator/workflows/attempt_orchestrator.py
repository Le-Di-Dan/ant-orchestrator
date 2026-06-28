"""AttemptOrchestrator — CAS-safe ExecutionAttempt lifecycle (PHASE_4_PLAN C.9/MICRO #3).

Owns the before/after side-effects around a single worker invocation:
- Before: recover any stale STARTED attempt (→ INDETERMINATE); create new STARTED.
- After: settle the attempt (SUCCEEDED or FAILED) based on worker outcome.

No exactly-once guarantee: the partial-unique index (PLANNED|STARTED per logical action)
is the only ordering guarantee in Phase 4. A real worker (Phase 5+) requires provider
idempotency and compensation mechanisms.
"""

from __future__ import annotations

from datetime import timedelta

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.application.services.workflow_support import UnitOfWorkFactory
from ant_orchestrator.config.constants import EXECUTION_ATTEMPT_LEASE_SECONDS
from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.value_objects import (
    ExecutionAttemptId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ExecutionAttempt
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator

_OUTCOME_STATUS: dict[WorkerOutcome, ExecutionAttemptStatus] = {
    WorkerOutcome.SUCCESS: ExecutionAttemptStatus.SUCCEEDED,
    WorkerOutcome.RETRYABLE_FAILURE: ExecutionAttemptStatus.FAILED,
    WorkerOutcome.PERMANENT_FAILURE: ExecutionAttemptStatus.FAILED,
    WorkerOutcome.VALIDATION_FAILURE: ExecutionAttemptStatus.FAILED,
    WorkerOutcome.REVIEW_REGROUP: ExecutionAttemptStatus.SUCCEEDED,
    WorkerOutcome.ESCALATION: ExecutionAttemptStatus.FAILED,
}


class AttemptOrchestrator:
    """Manages ExecutionAttempt lifecycle around a worker invocation.

    A stale STARTED attempt (owner_token lease expired) is marked INDETERMINATE before
    a new attempt is created. The orchestrator never marks a STARTED attempt FAILED
    without a confirmed outcome (MICRO #3 — INDETERMINATE ≠ FAILED).
    """

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock, ids: IdGenerator) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._ids = ids

    def before_execute(self, run_id: str, logical_action_id: str) -> str:
        """Ensure exactly one STARTED attempt is active; return its ID.

        If a non-stale STARTED attempt exists, re-use it (idempotent resume after crash).
        If a stale STARTED attempt exists, mark it INDETERMINATE and create a new one.
        """
        now = self._clock.now()
        run_id_vo = WorkflowRunId(run_id)
        with self._uow_factory() as uow:
            active = uow.execution_attempts.find_active(run_id_vo, logical_action_id)
            if active is not None:
                if self._is_stale(active, now):
                    uow.execution_attempts.update(
                        active.with_status(ExecutionAttemptStatus.INDETERMINATE, completed_at=now)
                    )
                else:
                    return active.id.value
            prev = uow.execution_attempts.list_for_action(run_id_vo, logical_action_id)
            attempt_no = max((a.attempt_no for a in prev), default=0) + 1
            lease = UtcTimestamp(now.value + timedelta(seconds=EXECUTION_ATTEMPT_LEASE_SECONDS))
            attempt = ExecutionAttempt(
                id=ExecutionAttemptId(self._ids.new_id()),
                workflow_run_id=run_id_vo,
                logical_action_id=logical_action_id,
                attempt_no=attempt_no,
                status=ExecutionAttemptStatus.STARTED,
                created_at=now,
                owner_token=self._ids.new_id(),
                lease_expires_at=lease,
                started_at=now,
            )
            uow.execution_attempts.add(attempt)
        return attempt.id.value

    def after_execute(self, attempt_id: str, outcome: WorkerOutcome) -> None:
        """Settle the attempt to SUCCEEDED or FAILED based on worker outcome."""
        now = self._clock.now()
        status = _OUTCOME_STATUS.get(outcome, ExecutionAttemptStatus.FAILED)
        with self._uow_factory() as uow:
            attempt = uow.execution_attempts.get(ExecutionAttemptId(attempt_id))
            uow.execution_attempts.update(attempt.with_status(status, completed_at=now))

    def get_attempt_no(self, attempt_id: str) -> int:
        """Return the ``attempt_no`` for a known attempt (used by Test Ant energy delta)."""
        with self._uow_factory() as uow:
            return uow.execution_attempts.get(ExecutionAttemptId(attempt_id)).attempt_no

    @staticmethod
    def _is_stale(attempt: ExecutionAttempt, now: UtcTimestamp) -> bool:
        """Return True when a STARTED attempt's owner lease has expired."""
        return (
            attempt.status is ExecutionAttemptStatus.STARTED
            and attempt.lease_expires_at is not None
            and attempt.lease_expires_at.value < now.value
        )
