"""Builds a genuine v3 database for v4 migration testing (test-only).

Intentionally composes real migrators rather than duplicating the full v3 DDL —
the purpose of this fixture is to provide a valid v3 starting point, not to
freeze a DDL snapshot of intermediate schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.migration_v2 import SqliteDatabaseMigrator
from ant_orchestrator.persistence.migration_v3 import SqliteDatabaseMigratorV3
from tests.support.legacy_schema_v1 import build_v1_database


class _FixedClock:
    def now(self) -> UtcTimestamp:
        return UtcTimestamp(datetime(2026, 6, 20, tzinfo=UTC))


def build_v3_database(db_path: Path, *, applied_at: str = "2026-06-20T00:00:00+00:00") -> None:
    """Create a genuine v3 database by migrating v1 → v2 → v3."""
    clock = _FixedClock()
    build_v1_database(db_path, applied_at=applied_at)
    SqliteDatabaseMigrator(clock).migrate(db_path)
    SqliteDatabaseMigratorV3(clock).migrate(db_path)
