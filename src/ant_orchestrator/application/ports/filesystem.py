"""Filesystem tool port: minimal text read/write contract (PHASE_2_PLAN §CP5).

Async, provider/OS-neutral. ``path`` is a workspace-relative string; real path
resolution and enforcement (allowlist, escape prevention) belong to Phase 3 — this
contract only expresses intent. Empty content is valid. No real I/O here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata
from ant_orchestrator.core.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class FileReadRequest:
    """Read the text at a workspace-relative ``path``."""

    path: str

    def __post_init__(self) -> None:
        if not self.path:
            raise InvariantViolation("FileReadRequest.path must be non-empty")


@dataclass(frozen=True, slots=True)
class FileReadResult:
    """The text read from ``path`` (``content`` may be empty)."""

    path: str
    content: str
    invocation: ToolInvocationMetadata


@dataclass(frozen=True, slots=True)
class FileWriteRequest:
    """Write ``content`` to a workspace-relative ``path``."""

    path: str
    content: str

    def __post_init__(self) -> None:
        if not self.path:
            raise InvariantViolation("FileWriteRequest.path must be non-empty")


@dataclass(frozen=True, slots=True)
class FileWriteResult:
    """The outcome of a write; ``changed`` is False when content was identical."""

    path: str
    changed: bool
    invocation: ToolInvocationMetadata


@runtime_checkable
class FileSystemAdapter(Protocol):
    """Async, workspace-relative text filesystem access."""

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        """Return the text at ``request.path`` or raise ``ToolNotFoundError``."""
        ...

    async def write_text(self, request: FileWriteRequest) -> FileWriteResult:
        """Write ``request.content`` and report whether it changed."""
        ...
