"""Stable mapping of error types to process exit codes (PHASE_1_PLAN §15.2)."""

from __future__ import annotations

from typing import Final

from ant_orchestrator.application.ports.database import DatabasePortError
from ant_orchestrator.application.ports.workspace import WorkspacePortError
from ant_orchestrator.config.errors import ConfigError

EXIT_OK: Final = 0
EXIT_UNEXPECTED: Final = 1
EXIT_CONFIG: Final = 2
EXIT_WORKSPACE: Final = 3
EXIT_PERSISTENCE: Final = 4


def exit_code_for(error: BaseException) -> int:
    """Return the exit code for a raised error."""
    if isinstance(error, ConfigError):
        return EXIT_CONFIG
    if isinstance(error, WorkspacePortError):
        return EXIT_WORKSPACE
    if isinstance(error, DatabasePortError):
        return EXIT_PERSISTENCE
    return EXIT_UNEXPECTED
