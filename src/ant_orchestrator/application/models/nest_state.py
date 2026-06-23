"""NestState aggregate combining workspace and database sub-states (D30).

The application service owns this aggregation because the workspace adapter cannot
inspect the database and vice versa.
"""

from __future__ import annotations

from enum import Enum

from ant_orchestrator.application.ports.database import DatabaseState
from ant_orchestrator.application.ports.workspace import WorkspaceArtifactState


class NestState(Enum):
    """Overall usability of a Nest."""

    ABSENT = "absent"
    CONFIGURED = "configured"
    READY = "ready"
    CORRUPTED = "corrupted"
    INCOMPATIBLE = "incompatible"


_DATABASE_TO_NEST = {
    DatabaseState.MISSING: NestState.CONFIGURED,
    DatabaseState.READY: NestState.READY,
    DatabaseState.CORRUPTED: NestState.CORRUPTED,
    DatabaseState.SCHEMA_INCOMPATIBLE: NestState.INCOMPATIBLE,
}


def aggregate(artifact: WorkspaceArtifactState, database: DatabaseState | None) -> NestState:
    """Combine the workspace artifact state and (optional) database state."""
    if artifact is WorkspaceArtifactState.ABSENT:
        return NestState.ABSENT
    if artifact is WorkspaceArtifactState.FILES_CORRUPTED:
        return NestState.CORRUPTED
    if artifact is WorkspaceArtifactState.WORKSPACE_FORMAT_INCOMPATIBLE:
        return NestState.INCOMPATIBLE
    if database is None:
        return NestState.CONFIGURED
    return _DATABASE_TO_NEST[database]
