"""Common base for SQLite repositories."""

from __future__ import annotations

import sqlite3

from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.persistence.database import Database


class SqliteRepository:
    """Holds the database handle for a repository (transaction-per-operation)."""

    def __init__(self, db: Database) -> None:
        self._db = db

    @staticmethod
    def _missing(entity: str, identifier: str) -> RecordNotFound:
        return RecordNotFound(f"{entity} {identifier} not found")


class ConnRepository:
    """Holds a single shared connection; never commits (a UnitOfWork owns the txn).

    Used by Phase 4 repositories that participate in a multi-mutation unit of work.
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @staticmethod
    def _missing(entity: str, identifier: str) -> RecordNotFound:
        return RecordNotFound(f"{entity} {identifier} not found")
