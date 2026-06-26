"""Application-layer errors (PHASE_1_PLAN §14)."""

from __future__ import annotations

from ant_orchestrator.errors import AntError


class ApplicationError(AntError):
    """Base class for application/use-case errors."""


class WorkflowStateError(ApplicationError):
    """A workflow command was issued against an incompatible task/run state."""


class ApprovalStateConflict(WorkflowStateError):
    """A resume was requested with a decision that conflicts with the persisted one."""


class ApprovalRuleViolation(WorkflowStateError):
    """An approval command was issued against a gate that does not permit it.

    Distinct from :class:`ApprovalStateConflict` (a conflicting *decision*): this
    signals the gate precondition itself is not satisfied (no pending approval, or
    the run is not awaiting approval). Maps to a dedicated CLI exit code.
    """


class CheckpointRecoveryError(WorkflowStateError):
    """A durable checkpoint was expected but is missing/incompatible (fail-closed)."""
