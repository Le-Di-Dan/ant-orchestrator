"""Checkpointer wrapper tests — separate file, lifecycle, isolation (CP3)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.workflows.checkpointer import open_checkpointer
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME, DATABASE_FILENAME
from tests.conftest import FakeClock


def _tables(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_checkpointer_creates_separate_file_with_langgraph_tables(tmp_path: Path) -> None:
    db_path = tmp_path / CHECKPOINT_DB_FILENAME
    with open_checkpointer(db_path) as saver:
        assert saver is not None
    assert db_path.exists()
    assert {"checkpoints", "writes"} <= _tables(db_path)


def test_checkpointer_closes_connection_on_exit(tmp_path: Path) -> None:
    db_path = tmp_path / CHECKPOINT_DB_FILENAME
    with open_checkpointer(db_path) as saver:
        conn = saver.conn
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_state_db_has_no_checkpointer_tables(tmp_path: Path, clock: FakeClock) -> None:
    state_path = tmp_path / DATABASE_FILENAME
    SqliteDatabaseBootstrapper(clock).bootstrap(state_path)
    tables = _tables(state_path)
    assert "checkpoints" not in tables
    assert "writes" not in tables
    # The two stores are entirely separate files.
    assert (tmp_path / CHECKPOINT_DB_FILENAME).exists() is False
