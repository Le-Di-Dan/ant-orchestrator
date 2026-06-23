"""SQLite connection lifecycle (PHASE_1_PLAN §13.2).

One connection per unit of work; foreign keys enforced; transaction-per-operation.
Connections are not shared across threads (sqlite3 default ``check_same_thread``).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class Database:
    """Owns a SQLite file path and hands out short-lived connections."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """Open a connection with foreign keys enabled; always closed afterwards."""
        conn = sqlite3.connect(str(self._path))
        try:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            yield conn
        finally:
            conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Run a single transaction: commit on success, rollback on any error."""
        with self.connect() as conn:
            try:
                yield conn
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
