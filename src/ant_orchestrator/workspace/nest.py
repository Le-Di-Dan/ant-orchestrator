"""Filesystem implementation of ``WorkspaceProvisioner`` (PHASE_1_PLAN §12).

Builds and publishes a ``.ant/`` Nest atomically via a staging directory, classifies
the artifact state, and refuses nested Nests. Database creation is delegated to an
injected callback so this module never imports sqlite3/persistence (D29).
"""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.application.ports.workspace import (
    BootstrapDatabase,
    NestedNestNotAllowed,
    WorkspaceArtifactState,
    WorkspacePermissionError,
)
from ant_orchestrator.config.constants import CONFIG_FILENAME
from ant_orchestrator.config.errors import ConfigError
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.workspace.atomic import discard, publish
from ant_orchestrator.workspace.discovery import find_ancestor_nest, find_nest
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    DATABASE_FILENAME,
    DB_TEMP_SUFFIX,
    GITIGNORE_FILENAME,
    GITIGNORE_LINES,
    GITKEEP_DIRS,
    MARKER_FILENAME,
    MARKER_KEY_CREATED_AT,
    MARKER_KEY_ID,
    MARKER_KEY_VERSION,
    STAGING_PREFIX,
    SUBDIRECTORIES,
    WORKSPACE_FORMAT_VERSION,
)


class FilesystemWorkspaceProvisioner:
    """Creates/inspects ``.ant/`` Nests on the local filesystem."""

    def __init__(self, clock: Clock, id_generator: IdGenerator) -> None:
        self._clock = clock
        self._ids = id_generator

    def find_root(self, start: Path) -> Path | None:
        return find_nest(start)

    def database_path(self, root: Path) -> Path:
        return root / ANT_DIRNAME / DATABASE_FILENAME

    def config_path(self, root: Path) -> Path:
        return root / ANT_DIRNAME / CONFIG_FILENAME

    def format_version(self, root: Path) -> int | None:
        return self._marker_version(root / ANT_DIRNAME / MARKER_FILENAME)

    def classify(self, root: Path) -> WorkspaceArtifactState:
        ant = root / ANT_DIRNAME
        if not ant.exists():
            return WorkspaceArtifactState.ABSENT
        if not ant.is_dir():
            return WorkspaceArtifactState.FILES_CORRUPTED
        config_path = ant / CONFIG_FILENAME
        marker_path = ant / MARKER_FILENAME
        if not config_path.is_file() or not marker_path.is_file():
            return WorkspaceArtifactState.FILES_CORRUPTED
        try:
            load_document(config_path)
        except ConfigError:
            return WorkspaceArtifactState.FILES_CORRUPTED
        version = self._marker_version(marker_path)
        if version is None:
            return WorkspaceArtifactState.FILES_CORRUPTED
        if version > WORKSPACE_FORMAT_VERSION:
            return WorkspaceArtifactState.WORKSPACE_FORMAT_INCOMPATIBLE
        return WorkspaceArtifactState.CONFIGURED

    def create_nest(self, root: Path, *, config_text: str, bootstrap_db: BootstrapDatabase) -> None:
        if find_ancestor_nest(root) is not None:
            raise NestedNestNotAllowed(f"An ancestor of {root} already contains {ANT_DIRNAME}/")
        staging = root / f"{STAGING_PREFIX}{self._ids.new_id()}"
        try:
            self._build_layout(staging, config_text)
            bootstrap_db(staging / DATABASE_FILENAME)
            publish(staging, root / ANT_DIRNAME)
        except PermissionError as exc:
            discard(staging)
            raise WorkspacePermissionError(str(exc)) from exc
        except BaseException:
            discard(staging)
            raise

    def provision_database(self, root: Path, *, bootstrap_db: BootstrapDatabase) -> None:
        ant = root / ANT_DIRNAME
        target = ant / DATABASE_FILENAME
        tmp = ant / f"{DATABASE_FILENAME}{DB_TEMP_SUFFIX}{self._ids.new_id()}"
        try:
            bootstrap_db(tmp)
            publish(tmp, target)
        except PermissionError as exc:
            discard(tmp)
            raise WorkspacePermissionError(str(exc)) from exc
        except BaseException:
            discard(tmp)
            raise

    def _build_layout(self, staging: Path, config_text: str) -> None:
        staging.mkdir(parents=True, exist_ok=False)
        for sub in SUBDIRECTORIES:
            (staging / sub).mkdir()
        (staging / CONFIG_FILENAME).write_text(config_text, encoding="utf-8")
        (staging / MARKER_FILENAME).write_text(self._marker_text(), encoding="utf-8")
        gitignore = "\n".join(GITIGNORE_LINES) + "\n"
        (staging / GITIGNORE_FILENAME).write_text(gitignore, encoding="utf-8")
        for keep_dir in GITKEEP_DIRS:
            (staging / keep_dir / ".gitkeep").write_text("", encoding="utf-8")

    def _marker_text(self) -> str:
        marker = {
            MARKER_KEY_ID: self._ids.new_id(),
            MARKER_KEY_VERSION: WORKSPACE_FORMAT_VERSION,
            MARKER_KEY_CREATED_AT: self._clock.now().to_iso(),
        }
        return json.dumps(marker, indent=2, sort_keys=True) + "\n"

    def _marker_version(self, marker_path: Path) -> int | None:
        try:
            raw = json.loads(marker_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(raw, dict):
            return None
        version = raw.get(MARKER_KEY_VERSION)
        if isinstance(version, bool) or not isinstance(version, int):
            return None
        return version
