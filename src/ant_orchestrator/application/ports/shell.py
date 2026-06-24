"""Shell tool port: argv-based process execution contract (PHASE_2_PLAN §CP5).

Async, OS-neutral. The request is ``argv`` (a token list), never a raw shell
string and never ``shell=True``. A non-zero ``exit_code`` is a valid completed
result, not an error. No real process execution here; enforcement is Phase 3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata
from ant_orchestrator.core.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class ShellRequest:
    """Run ``argv`` in an optional workspace-relative ``cwd`` with an optional timeout."""

    argv: tuple[str, ...]
    cwd: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if not self.argv:
            raise InvariantViolation("ShellRequest.argv must be non-empty")
        if not all(isinstance(token, str) for token in self.argv):
            raise InvariantViolation("ShellRequest.argv must contain only strings")
        # Only the executable (argv[0]) must be non-empty/non-whitespace; later
        # arguments may be empty or whitespace and are preserved verbatim.
        if not self.argv[0].strip():
            raise InvariantViolation("ShellRequest.argv[0] (executable) must be non-empty")
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise InvariantViolation("ShellRequest.timeout_seconds must be > 0")


@dataclass(frozen=True, slots=True)
class ShellResult:
    """A completed process result (any ``exit_code``; streams may be empty)."""

    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    invocation: ToolInvocationMetadata

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise InvariantViolation("ShellResult.duration_seconds must be >= 0")


@runtime_checkable
class ShellAdapter(Protocol):
    """Async argv-based process runner."""

    async def run(self, request: ShellRequest) -> ShellResult:
        """Run the process and return its completed result (no output parsing)."""
        ...
