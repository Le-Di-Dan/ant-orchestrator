"""Worker execution port — structured action intent and bounded outcomes (PHASE_4_PLAN C.11).

Framework-neutral and infra-free. A worker receives a *structured* action intent
(never free-form text that secretly steers behaviour) and returns a typed outcome.
Phase 4 ships only stub adapters; real side effects come in a later phase.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ant_orchestrator.core.domain.errors import InvariantViolation

# Bound on the sanitized detail a worker may attach to its outcome.
MAX_WORKER_DETAIL_CHARS = 2000


class WorkerOutcome(Enum):
    """Typed result of a single worker execution (PHASE_4_PLAN C.11)."""

    SUCCESS = "success"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    VALIDATION_FAILURE = "validation_failure"
    REVIEW_REGROUP = "review_regroup"
    ESCALATION = "escalation"


@dataclass(frozen=True, slots=True)
class WorkerActionIntent:
    """A structured, sanitized description of the action a worker should attempt.

    Behaviour-affecting decisions are explicit boolean/field flags — never inferred
    from ``summary`` text — so a task title can never covertly steer execution.
    """

    logical_action_id: str
    summary: str
    requires_significant_write: bool = False
    requires_unsafe_command: bool = False
    target_paths: tuple[str, ...] = ()
    command_argv: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.logical_action_id:
            raise InvariantViolation("WorkerActionIntent.logical_action_id must be non-empty")
        if len(self.summary) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("WorkerActionIntent.summary exceeds the bound")


@dataclass(frozen=True, slots=True)
class WorkerExecutionResult:
    """A bounded, sanitized worker result. No secrets, no raw provider output."""

    outcome: WorkerOutcome
    detail: str = ""
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if len(self.detail) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("WorkerExecutionResult.detail exceeds the bound")


@runtime_checkable
class WorkerExecutionPort(Protocol):
    """Synchronous worker execution boundary (sync per ADR-0002 / PHASE_4_PLAN C.1)."""

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        """Execute the structured intent and return a bounded, typed result."""
        ...
