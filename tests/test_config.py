"""Unit tests for the configuration layer (CP3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.config.constants import (
    CONFIG_DOCUMENT_VERSION,
    DEFAULT_PROJECT_NAME,
    ENV_PROJECT_NAME,
)
from ant_orchestrator.config.errors import ConfigInvalid, UnknownConfigKey
from ant_orchestrator.config.loader import dump_document, load_document
from ant_orchestrator.config.models import ProjectConfig, ResolvedConfig
from ant_orchestrator.config.resolver import ConfigResolver

# --- loader -------------------------------------------------------------------


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    assert load_document(tmp_path / "absent.yaml") == {}


def test_load_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("", encoding="utf-8")
    assert load_document(path) == {}


def test_load_non_mapping_root_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigInvalid):
        load_document(path)


def test_load_non_string_key_raises(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("1: value\n", encoding="utf-8")
    with pytest.raises(ConfigInvalid):
        load_document(path)


def test_load_valid_document(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("version: 1\nproject:\n  name: demo\n", encoding="utf-8")
    assert load_document(path) == {"version": 1, "project": {"name": "demo"}}


# --- resolver -----------------------------------------------------------------


def test_resolve_defaults_when_empty() -> None:
    cfg = ConfigResolver().resolve(file_data={}, env={})
    assert cfg == ResolvedConfig(
        version=CONFIG_DOCUMENT_VERSION, project=ProjectConfig(name=DEFAULT_PROJECT_NAME)
    )


def test_resolve_file_values() -> None:
    cfg = ConfigResolver().resolve(file_data={"version": 1, "project": {"name": "x"}}, env={})
    assert cfg.project.name == "x"


def test_unknown_top_level_key_rejected() -> None:
    with pytest.raises(UnknownConfigKey):
        ConfigResolver().resolve(file_data={"bogus": 1}, env={})


def test_unknown_nested_key_rejected() -> None:
    with pytest.raises(UnknownConfigKey):
        ConfigResolver().resolve(file_data={"project": {"nope": 1}}, env={})


def test_version_must_be_int() -> None:
    with pytest.raises(ConfigInvalid):
        ConfigResolver().resolve(file_data={"version": "1"}, env={})


def test_version_bool_rejected() -> None:
    with pytest.raises(ConfigInvalid):
        ConfigResolver().resolve(file_data={"version": True}, env={})


def test_version_below_one_rejected() -> None:
    with pytest.raises(ConfigInvalid):
        ConfigResolver().resolve(file_data={"version": 0}, env={})


def test_project_must_be_mapping() -> None:
    with pytest.raises(ConfigInvalid):
        ConfigResolver().resolve(file_data={"project": "oops"}, env={})


def test_project_name_must_be_string() -> None:
    with pytest.raises(ConfigInvalid):
        ConfigResolver().resolve(file_data={"project": {"name": 123}}, env={})


def test_env_overrides_file() -> None:
    cfg = ConfigResolver().resolve(
        file_data={"project": {"name": "from_file"}},
        env={ENV_PROJECT_NAME: "from_env"},
    )
    assert cfg.project.name == "from_env"


def test_dump_load_roundtrip(tmp_path: Path) -> None:
    config = ResolvedConfig(version=1, project=ProjectConfig(name="demo"))
    path = tmp_path / "config.yaml"
    path.write_text(dump_document(config), encoding="utf-8")
    resolved = ConfigResolver().resolve(file_data=load_document(path), env={})
    assert resolved == config
