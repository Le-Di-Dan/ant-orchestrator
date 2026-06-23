"""Integration tests for the workspace adapter (CP5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import FakeClock, SequentialIdGenerator

from ant_orchestrator.application.ports.workspace import (
    NestedNestNotAllowed,
    NestNotFound,
    WorkspaceArtifactState,
)
from ant_orchestrator.config.constants import CONFIG_FILENAME
from ant_orchestrator.workspace.discovery import discover, find_nest
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    DATABASE_FILENAME,
    GITIGNORE_LINES,
    MARKER_FILENAME,
    MARKER_KEY_VERSION,
    SUBDIRECTORIES,
)
from ant_orchestrator.workspace.nest import FilesystemWorkspaceProvisioner


def _provisioner(clock: FakeClock, id_gen: SequentialIdGenerator) -> FilesystemWorkspaceProvisioner:
    return FilesystemWorkspaceProvisioner(clock, id_gen)


def _fake_bootstrap(db_path: Path) -> None:
    db_path.write_text("db", encoding="utf-8")


def test_classify_absent(tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator) -> None:
    assert _provisioner(clock, id_gen).classify(tmp_path) is WorkspaceArtifactState.ABSENT


def test_create_nest_builds_full_layout(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    provisioner = _provisioner(clock, id_gen)
    provisioner.create_nest(tmp_path, config_text="version: 1\n", bootstrap_db=_fake_bootstrap)
    ant = tmp_path / ANT_DIRNAME
    assert (ant / CONFIG_FILENAME).read_text(encoding="utf-8") == "version: 1\n"
    assert (ant / MARKER_FILENAME).is_file()
    assert (ant / DATABASE_FILENAME).is_file()
    for sub in SUBDIRECTORIES:
        assert (ant / sub).is_dir()
    assert (ant / "tasks" / ".gitkeep").is_file()
    assert provisioner.classify(tmp_path) is WorkspaceArtifactState.CONFIGURED
    assert not list(tmp_path.glob(".ant.tmp-*"))


def test_gitignore_content(tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator) -> None:
    _provisioner(clock, id_gen).create_nest(
        tmp_path, config_text="version: 1\n", bootstrap_db=_fake_bootstrap
    )
    text = (tmp_path / ANT_DIRNAME / ".gitignore").read_text(encoding="utf-8")
    assert text.splitlines() == list(GITIGNORE_LINES)


def test_create_nest_rejects_nested(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    provisioner = _provisioner(clock, id_gen)
    provisioner.create_nest(tmp_path, config_text="version: 1\n", bootstrap_db=_fake_bootstrap)
    child = tmp_path / "child"
    child.mkdir()
    with pytest.raises(NestedNestNotAllowed):
        provisioner.create_nest(child, config_text="version: 1\n", bootstrap_db=_fake_bootstrap)


def test_provision_database_adds_db(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    provisioner = _provisioner(clock, id_gen)
    # Build a CONFIGURED nest by hand (no database), simulating a fresh git clone.
    ant = tmp_path / ANT_DIRNAME
    ant.mkdir()
    (ant / CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")
    (ant / MARKER_FILENAME).write_text(json.dumps({MARKER_KEY_VERSION: 1}), encoding="utf-8")
    assert provisioner.classify(tmp_path) is WorkspaceArtifactState.CONFIGURED
    provisioner.provision_database(tmp_path, bootstrap_db=_fake_bootstrap)
    assert (ant / DATABASE_FILENAME).is_file()


def test_classify_files_corrupted_without_marker(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    ant = tmp_path / ANT_DIRNAME
    ant.mkdir()
    (ant / CONFIG_FILENAME).write_text("version: 1\n", encoding="utf-8")
    assert _provisioner(clock, id_gen).classify(tmp_path) is WorkspaceArtifactState.FILES_CORRUPTED


def test_classify_format_incompatible(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    provisioner = _provisioner(clock, id_gen)
    provisioner.create_nest(tmp_path, config_text="version: 1\n", bootstrap_db=_fake_bootstrap)
    marker = tmp_path / ANT_DIRNAME / MARKER_FILENAME
    marker.write_text(json.dumps({MARKER_KEY_VERSION: 99}), encoding="utf-8")
    assert provisioner.classify(tmp_path) is WorkspaceArtifactState.WORKSPACE_FORMAT_INCOMPATIBLE


def test_staging_cleaned_on_bootstrap_failure(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    def boom(_db_path: Path) -> None:
        raise RuntimeError("bootstrap failed")

    with pytest.raises(RuntimeError):
        _provisioner(clock, id_gen).create_nest(
            tmp_path, config_text="version: 1\n", bootstrap_db=boom
        )
    assert not (tmp_path / ANT_DIRNAME).exists()
    assert not list(tmp_path.glob(".ant.tmp-*"))


def test_discovery_walks_up(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    _provisioner(clock, id_gen).create_nest(
        tmp_path, config_text="version: 1\n", bootstrap_db=_fake_bootstrap
    )
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert discover(nested) == tmp_path.resolve()
    assert find_nest(nested) == tmp_path.resolve()


def test_discovery_not_found(
    tmp_path: Path, clock: FakeClock, id_gen: SequentialIdGenerator
) -> None:
    with pytest.raises(NestNotFound):
        discover(tmp_path)
