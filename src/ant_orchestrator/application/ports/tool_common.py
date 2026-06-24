"""Shared tool-port value types (PHASE_2_PLAN §CP5).

``ToolInvocationMetadata`` is the minimal "tool invocation record" the roadmap
asks for: enough structured evidence to know which tool/operation completed. It is
not persisted, logged or tied to energy/approval here, and never carries
command/content/output.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.core.domain.errors import InvariantViolation


class ToolKind(Enum):
    """Category of tool behind a port."""

    FILESYSTEM = "filesystem"
    SHELL = "shell"
    TEST_RUNNER = "test_runner"
    GIT = "git"


@dataclass(frozen=True, slots=True)
class ToolInvocationMetadata:
    """Neutral evidence that a tool operation completed (no sensitive payload)."""

    tool: ToolKind
    operation: str

    def __post_init__(self) -> None:
        if not self.operation:
            raise InvariantViolation("ToolInvocationMetadata.operation must be non-empty")
