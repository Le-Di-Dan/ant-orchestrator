"""InitNest use case: create or provision a Nest atomically (PHASE_1_PLAN §12.3)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.models.outcomes import InitNestOutcome
from ant_orchestrator.application.ports.database import (
    DatabaseBootstrapper,
    DatabaseInspector,
    DatabaseState,
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.application.ports.workspace import (
    NestCorrupted,
    NestFormatIncompatible,
    WorkspaceArtifactState,
    WorkspaceProvisioner,
)
from ant_orchestrator.config.constants import CONFIG_DOCUMENT_VERSION, DEFAULT_PROJECT_NAME
from ant_orchestrator.config.loader import dump_document
from ant_orchestrator.config.models import ProjectConfig, ResolvedConfig


class InitNestService:
    """Initialises a Nest, branching on the workspace/database state."""

    def __init__(
        self,
        provisioner: WorkspaceProvisioner,
        bootstrapper: DatabaseBootstrapper,
        inspector: DatabaseInspector,
    ) -> None:
        self._provisioner = provisioner
        self._bootstrapper = bootstrapper
        self._inspector = inspector

    def init(self, root: Path) -> InitNestOutcome:
        artifact = self._provisioner.classify(root)
        if artifact is WorkspaceArtifactState.ABSENT:
            self._provisioner.create_nest(
                root,
                config_text=self._default_config_text(root),
                bootstrap_db=self._bootstrapper.bootstrap,
            )
            return InitNestOutcome.CREATED
        if artifact is WorkspaceArtifactState.FILES_CORRUPTED:
            raise NestCorrupted(f"{root} contains a corrupted .ant/ workspace")
        if artifact is WorkspaceArtifactState.WORKSPACE_FORMAT_INCOMPATIBLE:
            raise NestFormatIncompatible(f"{root} has an incompatible workspace format")
        return self._init_configured(root)

    def _init_configured(self, root: Path) -> InitNestOutcome:
        db_state = self._inspector.classify(self._provisioner.database_path(root))
        if db_state is DatabaseState.MISSING:
            self._provisioner.provision_database(root, bootstrap_db=self._bootstrapper.bootstrap)
            return InitNestOutcome.PROVISIONED
        if db_state is DatabaseState.READY:
            return InitNestOutcome.ALREADY_INITIALIZED
        if db_state is DatabaseState.CORRUPTED:
            raise StorageIntegrityError(f"{root} has a corrupted database")
        raise SchemaVersionMismatch(f"{root} has an incompatible database schema")

    @staticmethod
    def _default_config_text(root: Path) -> str:
        name = root.resolve().name or DEFAULT_PROJECT_NAME
        config = ResolvedConfig(version=CONFIG_DOCUMENT_VERSION, project=ProjectConfig(name=name))
        return dump_document(config)
