"""Database outbound ports: bootstrap and inspection (PHASE_1_PLAN §12.2/§13.2).

Implemented by the persistence (SQLite) adapter. The application never imports
sqlite3 directly.

Port-owned error hierarchy lives here so ``application/services`` never imports
the concrete ``persistence`` adapter package.
"""

from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Protocol

from ant_orchestrator.errors import AntError

# ---------------------------------------------------------------------------
# Port error hierarchy (exit code 4)
# ---------------------------------------------------------------------------


class DatabasePortError(AntError):
    """Base class for database/persistence port errors (maps to CLI exit 4)."""


class SchemaVersionMismatch(DatabasePortError):
    """The database schema version is newer than this application supports."""


class StorageIntegrityError(DatabasePortError):
    """The database file is malformed or has an inconsistent schema."""


class RecordNotFound(DatabasePortError):
    """A requested record does not exist."""


# ---------------------------------------------------------------------------
# State enum + protocols
# ---------------------------------------------------------------------------


class DatabaseState(Enum):
    """Classification of the local runtime database (owner: persistence adapter)."""

    MISSING = "missing"
    READY = "ready"
    CORRUPTED = "corrupted"
    SCHEMA_INCOMPATIBLE = "schema_incompatible"


class DatabaseBootstrapper(Protocol):
    """Creates schema v1 in a fresh database file (idempotent, integrity-checked)."""

    def bootstrap(self, db_path: Path) -> None: ...


class DatabaseInspector(Protocol):
    """Classifies the state of a database file without mutating it."""

    def classify(self, db_path: Path) -> DatabaseState: ...

    def schema_version(self, db_path: Path) -> int | None:
        """Return the database schema version, or ``None`` if unavailable."""
        ...
