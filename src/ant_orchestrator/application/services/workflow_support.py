"""Shared helpers for the Phase 4 workflow services (PHASE_4_PLAN C.5/C.7/C.13).

Pure, infra-light utilities: deterministic identifiers (thread id, pause/completion
operation ids), a status-transition appender, and the framework-neutral outcome
returned by the workflow use-cases. Operation ids are stable so a replay reuses the
same idempotency key instead of appending a duplicate transition.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ant_orchestrator.config.constants import (
    COMPLETION_OPERATION_PREFIX,
    PAUSE_OPERATION_PREFIX,
)
from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    TransitionSubject,
    TransitionTrigger,
)
from ant_orchestrator.core.domain.records import Approval
from ant_orchestrator.core.domain.value_objects import TransitionId, UtcTimestamp, WorkflowRunId
from ant_orchestrator.core.domain.workflow import StatusTransition
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.core.ports.repositories import StatusTransitionRepository
from ant_orchestrator.core.ports.unit_of_work import UnitOfWork

# A unit of work is created per logical operation; the factory hides the concrete
# ``SqliteUnitOfWork`` from the application services (kept infra-free).
UnitOfWorkFactory = Callable[[], UnitOfWork]

_THREAD_PREFIX = "wf:"
_KEY_SEP = "\x1f"


def thread_id_for(run_id: str) -> str:
    """Return the deterministic LangGraph thread id for a workflow run."""
    return f"{_THREAD_PREFIX}{run_id}"


def pause_operation_id(gate_instance_id: str) -> str:
    """Stable idempotency key for finalizing a pause at a given gate occurrence."""
    return f"{PAUSE_OPERATION_PREFIX}{gate_instance_id}"


def completion_operation_id(run_id: str, checkpoint_id: str) -> str:
    """Stable idempotency key for finalizing completion at a final checkpoint."""
    key = _KEY_SEP.join((run_id, checkpoint_id))
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{COMPLETION_OPERATION_PREFIX}{digest}"


def append_transition(
    repo: StatusTransitionRepository,
    *,
    ids: IdGenerator,
    now: UtcTimestamp,
    run_id: WorkflowRunId,
    subject: TransitionSubject,
    to_status: str,
    trigger: TransitionTrigger,
    operation_id: str,
    from_status: str | None = None,
) -> None:
    """Append one append-only lifecycle transition (idempotent by operation_id)."""
    repo.append(
        StatusTransition(
            id=TransitionId(ids.new_id()),
            workflow_run_id=run_id,
            subject=subject,
            to_status=to_status,
            trigger=trigger,
            operation_id=operation_id,
            created_at=now,
            from_status=from_status,
        )
    )


def latest_persisted_decision(approvals: Sequence[Approval]) -> ApprovalStatus | None:
    """Return the most recent *resolved* approval decision for a task (or ``None``).

    ``approvals`` must be ordered oldest-first (``list_by_task``). Used so a resolve
    on an already-terminal task is classified as an idempotent replay (same decision)
    or a conflict (different decision) instead of an unconditional terminal return.
    """
    resolved = [approval.status for approval in approvals if approval.status.is_terminal]
    return resolved[-1] if resolved else None


@dataclass(frozen=True, slots=True)
class WorkflowOutcome:
    """Framework-neutral result of a workflow command (no domain/LangGraph types)."""

    status: str
    run_id: str
    final_outcome: str | None = None
    approval_id: str | None = None
    resume_operation_id: str | None = None
    resumed: bool = False
