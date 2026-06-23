"""GetNestStatus use case: report the aggregate state of a discovered Nest."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.models.nest_state import aggregate
from ant_orchestrator.application.models.views import NestStatusView
from ant_orchestrator.application.ports.database import DatabaseInspector
from ant_orchestrator.application.ports.workspace import (
    NestNotFound,
    WorkspaceArtifactState,
    WorkspaceProvisioner,
)


class GetNestStatusService:
    """Discovers a Nest and reports its aggregate state and versions."""

    def __init__(self, provisioner: WorkspaceProvisioner, inspector: DatabaseInspector) -> None:
        self._provisioner = provisioner
        self._inspector = inspector

    def status(self, start: Path) -> NestStatusView:
        root = self._provisioner.find_root(start)
        if root is None:
            raise NestNotFound(f"No .ant/ found from {start}")
        artifact = self._provisioner.classify(root)
        db_path = self._provisioner.database_path(root)
        db_state = (
            self._inspector.classify(db_path)
            if artifact is WorkspaceArtifactState.CONFIGURED
            else None
        )
        return NestStatusView(
            root=root,
            state=aggregate(artifact, db_state),
            workspace_format_version=self._provisioner.format_version(root),
            schema_version=self._inspector.schema_version(db_path),
        )
