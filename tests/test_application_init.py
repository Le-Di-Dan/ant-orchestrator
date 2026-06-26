"""Tests for application services and the NestState aggregate (CP7)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.application.models.nest_state import NestState, aggregate
from ant_orchestrator.application.models.outcomes import InitNestOutcome
from ant_orchestrator.application.ports.database import (
    DatabaseState,
    SchemaVersionMismatch,
    StorageIntegrityError,
)
from ant_orchestrator.application.ports.workspace import (
    NestCorrupted,
    NestedNestNotAllowed,
    NestNotFound,
    WorkspaceArtifactState,
)
from ant_orchestrator.application.services.init_nest import InitNestService
from ant_orchestrator.application.services.nest_status import GetNestStatusService
from ant_orchestrator.application.services.show_config import ShowResolvedConfigService
from ant_orchestrator.config.constants import CONFIG_FILENAME
from ant_orchestrator.config.resolver import ConfigResolver
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
from ant_orchestrator.persistence.schema import MIGRATIONS_TABLE
from ant_orchestrator.workspace.layout import ANT_DIRNAME, MARKER_FILENAME
from ant_orchestrator.workspace.nest import FilesystemWorkspaceProvisioner
from tests.conftest import FakeClock, SequentialIdGenerator


def _init_service(clock: FakeClock, id_gen: SequentialIdGenerator) -> InitNestService:
    provisioner = FilesystemWorkspaceProvisioner(clock, id_gen)
    return InitNestService(
        provisioner, SqliteDatabaseBootstrapper(clock), SqliteDatabaseInspector()
    )


def _status_service(clock: FakeClock, id_gen: SequentialIdGenerator) -> GetNestStatusService:
    provisioner = FilesystemWorkspaceProvisioner(clock, id_gen)
    return GetNestStatusService(provisioner, SqliteDatabaseInspector())


# --- NestState aggregate matrix ----------------------------------------------


def test_aggregate_matrix() -> None:
    art = WorkspaceArtifactState
    db = DatabaseState
    assert aggregate(art.ABSENT, None) is NestState.ABSENT
    assert aggregate(art.FILES_CORRUPTED, None) is NestState.CORRUPTED
    assert aggregate(art.WORKSPACE_FORMAT_INCOMPATIBLE, None) is NestState.INCOMPATIBLE
    assert aggregate(art.CONFIGURED, db.MISSING) is NestState.CONFIGURED
    assert aggregate(art.CONFIGURED, db.READY) is NestState.READY
    assert aggregate(art.CONFIGURED, db.CORRUPTED) is NestState.CORRUPTED
    assert aggregate(art.CONFIGURED, db.SCHEMA_INCOMPATIBLE) is NestState.INCOMPATIBLE


# --- InitNest -----------------------------------------------------------------


def test_init_absent_creates_then_idempotent(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    service = _init_service(clock, id_gen)
    assert service.init(tmp_path) is InitNestOutcome.CREATED
    assert service.init(tmp_path) is InitNestOutcome.ALREADY_INITIALIZED
    assert _status_service(clock, id_gen).status(tmp_path).state is NestState.READY


def test_init_configured_clone_provisions(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    service = _init_service(clock, id_gen)
    service.init(tmp_path)
    # Simulate a fresh git clone: versioned files kept, runtime DB absent.
    (tmp_path / ANT_DIRNAME / "state.sqlite").unlink()
    assert service.init(tmp_path) is InitNestOutcome.PROVISIONED
    assert _status_service(clock, id_gen).status(tmp_path).state is NestState.READY


def test_init_rejects_nested(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    service = _init_service(clock, id_gen)
    service.init(tmp_path)
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(NestedNestNotAllowed):
        service.init(child)


def test_init_files_corrupted_does_not_mutate(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    ant = tmp_path / ANT_DIRNAME
    ant.mkdir()
    (ant / CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")  # marker missing
    with pytest.raises(NestCorrupted):
        _init_service(clock, id_gen).init(tmp_path)
    assert not (ant / MARKER_FILENAME).exists()  # untouched


def test_init_corrupted_database(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    service = _init_service(clock, id_gen)
    service.init(tmp_path)
    (tmp_path / ANT_DIRNAME / "state.sqlite").write_bytes(b"garbage")
    with pytest.raises(StorageIntegrityError):
        service.init(tmp_path)


def test_init_incompatible_schema(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    service = _init_service(clock, id_gen)
    service.init(tmp_path)
    with sqlite3.connect(str(tmp_path / ANT_DIRNAME / "state.sqlite")) as conn:
        # A version strictly newer than CODE_MAX_VERSION (now 2).
        conn.execute(f"INSERT INTO {MIGRATIONS_TABLE} VALUES (3, '2026-06-22T00:00:00+00:00')")
    with pytest.raises(SchemaVersionMismatch):
        service.init(tmp_path)


# --- status / config ----------------------------------------------------------


def test_status_not_found(tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator) -> None:
    with pytest.raises(NestNotFound):
        _status_service(clock, id_gen).status(tmp_path)


def test_show_config_after_init(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    _init_service(clock, id_gen).init(tmp_path)
    provisioner = FilesystemWorkspaceProvisioner(clock, id_gen)
    service = ShowResolvedConfigService(provisioner, ConfigResolver(), {})
    view = service.show(tmp_path)
    assert view.config.version == 1
    assert view.config.project.name == tmp_path.resolve().name


def test_show_config_corrupted(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    ant = tmp_path / ANT_DIRNAME
    ant.mkdir()
    (ant / CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")  # marker missing
    provisioner = FilesystemWorkspaceProvisioner(clock, id_gen)
    service = ShowResolvedConfigService(provisioner, ConfigResolver(), {})
    with pytest.raises(NestCorrupted):
        service.show(tmp_path)
