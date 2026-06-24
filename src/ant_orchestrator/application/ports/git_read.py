"""Git read-only tool port: status & diff/change evidence (PHASE_2_PLAN §CP5).

Strictly read-only — there is deliberately NO add/commit/push/pull/merge/reset/
checkout/branch/tag/stash/restore/apply or any other mutating operation. Async and
GitPython-neutral. A dirty repo and an empty diff are valid results, not errors. No
real git invocation here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata
from ant_orchestrator.core.domain.errors import InvariantViolation


class ChangeKind(Enum):
    """Neutral classification of a changed path."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"
    UNTRACKED = "untracked"


@dataclass(frozen=True, slots=True)
class GitChange:
    """A single changed path with its kind and staged flag."""

    path: str
    change_kind: ChangeKind
    staged: bool = False

    def __post_init__(self) -> None:
        if not self.path:
            raise InvariantViolation("GitChange.path must be non-empty")


@dataclass(frozen=True, slots=True)
class GitStatusRequest:
    """Request for the working-tree status (no parameters in Phase 2)."""


@dataclass(frozen=True, slots=True)
class GitStatusResult:
    """Working-tree status; ``is_clean`` implies no entries."""

    entries: tuple[GitChange, ...]
    is_clean: bool
    invocation: ToolInvocationMetadata

    def __post_init__(self) -> None:
        if self.is_clean and self.entries:
            raise InvariantViolation("GitStatusResult.is_clean cannot have entries")


@dataclass(frozen=True, slots=True)
class GitDiffRequest:
    """Request a diff; ``staged`` selects staged vs working changes."""

    staged: bool = False


@dataclass(frozen=True, slots=True)
class GitDiffResult:
    """Diff/change evidence; ``diff_text`` may be empty (no changes)."""

    changes: tuple[GitChange, ...]
    diff_text: str
    invocation: ToolInvocationMetadata


@runtime_checkable
class GitReadAdapter(Protocol):
    """Async, read-only git access (status + diff only)."""

    async def status(self, request: GitStatusRequest) -> GitStatusResult:
        """Return the working-tree status."""
        ...

    async def diff(self, request: GitDiffRequest) -> GitDiffResult:
        """Return diff/change evidence (empty diff is valid)."""
        ...
