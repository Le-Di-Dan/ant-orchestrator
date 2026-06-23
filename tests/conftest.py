"""Shared test fakes and fixtures (test-only; not production code)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper


class FakeClock:
    """A Clock returning a fixed instant for deterministic tests."""

    def __init__(self, moment: UtcTimestamp) -> None:
        self._moment = moment

    def now(self) -> UtcTimestamp:
        return self._moment


class SequentialIdGenerator:
    """An IdGenerator yielding predictable, monotonically increasing ids."""

    def __init__(self, prefix: str = "ID") -> None:
        self._prefix = prefix
        self._counter = 0

    def new_id(self) -> str:
        self._counter += 1
        return f"{self._prefix}-{self._counter:04d}"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC)))


@pytest.fixture
def id_gen() -> SequentialIdGenerator:
    return SequentialIdGenerator()


@pytest.fixture
def database(tmp_path: Path, clock: FakeClock) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    return Database(db_path)
