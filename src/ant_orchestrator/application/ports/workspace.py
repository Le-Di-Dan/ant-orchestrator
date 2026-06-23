"""Workspace outbound port: filesystem lifecycle of the ``.ant/`` Nest.

Implemented by the workspace adapter, which never imports sqlite3/persistence.
Database bootstrap is injected as a callback so the workspace can stage and
publish atomically while persistence owns DB creation (PHASE_1_PLAN §12.4, D29).

Port-owned error hierarchy lives here so ``application/services`` never imports
the concrete ``workspace`` adapter package.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from pathlib import Path
from typing import Protocol

from ant_orchestrator.errors import AntError

BootstrapDatabase = Callable[[Path], None]


# ---------------------------------------------------------------------------
# Port error hierarchy (exit code 3)
# ---------------------------------------------------------------------------


class WorkspacePortError(AntError):
    """Base class for workspace port errors (maps to CLI exit 3)."""


class NestNotFound(WorkspacePortError):
    """No ``.ant/`` workspace was found while walking up from a directory."""


class NestCorrupted(WorkspacePortError):
    """A ``.ant/`` exists but is missing required versioned files or is malformed."""


class NestFormatIncompatible(WorkspacePortError):
    """The workspace marker format version is newer than this application supports."""


class NestedNestNotAllowed(WorkspacePortError):
    """Refused to create a Nest because an ancestor directory already has one."""


class WorkspacePermissionError(WorkspacePortError):
    """A filesystem permission prevented a workspace operation."""


# ---------------------------------------------------------------------------
# State enum + protocol
# ---------------------------------------------------------------------------


class WorkspaceArtifactState(Enum):
    """Classification of versioned `.ant/` artifacts (owner: workspace adapter)."""

    ABSENT = "absent"
    CONFIGURED = "configured"
    FILES_CORRUPTED = "files_corrupted"
    WORKSPACE_FORMAT_INCOMPATIBLE = "workspace_format_incompatible"


class WorkspaceProvisioner(Protocol):
    """Filesystem lifecycle for a Nest: classify, create, provision, locate."""

    def classify(self, root: Path) -> WorkspaceArtifactState: ...

    def find_root(self, start: Path) -> Path | None:
        """Walk up from ``start`` to the nearest directory containing ``.ant/``."""
        ...

    def database_path(self, root: Path) -> Path: ...

    def config_path(self, root: Path) -> Path: ...

    def format_version(self, root: Path) -> int | None:
        """Return the workspace marker format version, or ``None`` if unreadable."""
        ...

    def create_nest(self, root: Path, *, config_text: str, bootstrap_db: BootstrapDatabase) -> None:
        """Atomically create a full Nest at ``root`` (ABSENT → READY)."""
        ...

    def provision_database(self, root: Path, *, bootstrap_db: BootstrapDatabase) -> None:
        """Atomically add ``state.sqlite`` to a CONFIGURED Nest (→ READY)."""
        ...
