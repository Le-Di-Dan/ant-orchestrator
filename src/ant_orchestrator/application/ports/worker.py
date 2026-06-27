"""Worker execution port — structured action intent and bounded outcomes (PHASE_4_PLAN C.11).

Framework-neutral and infra-free. A worker receives a *structured* action intent
(never free-form text that secretly steers behaviour) and returns a typed outcome.
Phase 4 ships only stub adapters; real side effects come in a later phase.
"""

from __future__ import annotations

from collections.abc import Mapping
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
    requires_energy_approval: bool = False
    target_paths: tuple[str, ...] = ()
    command_argv: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.logical_action_id:
            raise InvariantViolation("WorkerActionIntent.logical_action_id must be non-empty")
        if len(self.summary) > MAX_WORKER_DETAIL_CHARS:
            raise InvariantViolation("WorkerActionIntent.summary exceeds the bound")

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict for inclusion in graph state (no behaviour text)."""
        return {
            "logical_action_id": self.logical_action_id,
            "summary": self.summary,
            "requires_significant_write": self.requires_significant_write,
            "requires_unsafe_command": self.requires_unsafe_command,
            "requires_energy_approval": self.requires_energy_approval,
            "target_paths": list(self.target_paths),
            "command_argv": list(self.command_argv),
        }

    @classmethod
    def from_state_dict(cls, data: Mapping[str, object], *, default_id: str) -> WorkerActionIntent:
        """Rebuild a structured intent from a JSON-safe graph-state dict."""
        _tgt = data.get("target_paths")
        _cmd = data.get("command_argv")
        return cls(
            logical_action_id=str(data.get("logical_action_id") or default_id),
            summary=str(data.get("summary") or "stub action"),
            requires_significant_write=bool(data.get("requires_significant_write", False)),
            requires_unsafe_command=bool(data.get("requires_unsafe_command", False)),
            requires_energy_approval=bool(data.get("requires_energy_approval", False)),
            target_paths=tuple(str(p) for p in (_tgt if isinstance(_tgt, (list, tuple)) else ())),
            command_argv=tuple(str(a) for a in (_cmd if isinstance(_cmd, (list, tuple)) else ())),
        )


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
