"""Common base for SQLite repositories."""

from __future__ import annotations

from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.persistence.database import Database


class SqliteRepository:
    """Holds the database handle for a repository."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _missing(entity: str, identifier: str) -> RecordNotFound:
        return RecordNotFound(f"{entity} {identifier} not found")
