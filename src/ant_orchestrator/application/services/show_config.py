"""ShowResolvedConfig use case: resolve config after validating the workspace."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from ant_orchestrator.application.models.views import ResolvedConfigView
from ant_orchestrator.application.ports.workspace import (
    NestCorrupted,
    NestFormatIncompatible,
    NestNotFound,
    WorkspaceArtifactState,
    WorkspaceProvisioner,
)
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.config.resolver import ConfigResolver


class ShowResolvedConfigService:
    """Resolves configuration for the discovered Nest; never hides corruption."""

    def __init__(
        self,
        provisioner: WorkspaceProvisioner,
        resolver: ConfigResolver,
        env: Mapping[str, str],
    ) -> None:
        self._provisioner = provisioner
        self._resolver = resolver
        self._env = env

    def show(self, start: Path) -> ResolvedConfigView:
        root = self._provisioner.find_root(start)
        if root is None:
            raise NestNotFound(f"No .ant/ found from {start}")
        artifact = self._provisioner.classify(root)
        if artifact is WorkspaceArtifactState.FILES_CORRUPTED:
            raise NestCorrupted(f"{root} contains a corrupted .ant/ workspace")
        if artifact is WorkspaceArtifactState.WORKSPACE_FORMAT_INCOMPATIBLE:
            raise NestFormatIncompatible(f"{root} has an incompatible workspace format")
        file_data = load_document(self._provisioner.config_path(root))
        config = self._resolver.resolve(file_data=file_data, env=self._env)
        return ResolvedConfigView(root=root, config=config)
