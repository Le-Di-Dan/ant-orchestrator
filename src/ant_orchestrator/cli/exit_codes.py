"""Stable mapping of error types to process exit codes.

Phase 1 (§15.2): 0 ok, 1 unexpected, 2 usage/validation, 3 workspace, 4 storage.
Phase 4 CP7 adds: 5 state conflict, 6 approval rule violation. The order below is
significant — more specific subclasses are matched before their base classes.
"""

from __future__ import annotations

from typing import Final

from ant_orchestrator.application.errors import (
    ApprovalRuleViolation,
    ApprovalStateConflict,
    CheckpointRecoveryError,
    WorkflowStateError,
)
from ant_orchestrator.application.ports.database import DatabasePortError
from ant_orchestrator.application.ports.workspace import WorkspacePortError
from ant_orchestrator.config.errors import ConfigError
from ant_orchestrator.core.domain.errors import DomainError

EXIT_OK: Final = 0
EXIT_UNEXPECTED: Final = 1
EXIT_USAGE: Final = 2
EXIT_WORKSPACE: Final = 3
EXIT_PERSISTENCE: Final = 4
EXIT_STATE_CONFLICT: Final = 5
EXIT_APPROVAL_RULE: Final = 6


def exit_code_for(error: BaseException) -> int:
    """Return the stable exit code for a raised error (specific types first)."""
    # Recovery/storage is classified before the WorkflowStateError base so a missing
    # checkpoint after progress is never mistaken for a state conflict (CP7 §12).
    if isinstance(error, CheckpointRecoveryError):
        return EXIT_PERSISTENCE
    if isinstance(error, ApprovalRuleViolation):
        return EXIT_APPROVAL_RULE
    if isinstance(error, ApprovalStateConflict):
        return EXIT_STATE_CONFLICT
    if isinstance(error, WorkflowStateError):
        return EXIT_STATE_CONFLICT
    if isinstance(error, ConfigError):
        return EXIT_USAGE
    if isinstance(error, DomainError):
        return EXIT_USAGE
    if isinstance(error, WorkspacePortError):
        return EXIT_WORKSPACE
    if isinstance(error, DatabasePortError):
        return EXIT_PERSISTENCE
    return EXIT_UNEXPECTED
