"""Durable LangGraph checkpointer wrapper (PHASE_4_PLAN C.4).

Opens a ``SqliteSaver`` over the separate ``.ant/checkpoints.sqlite`` file with a
*no-pickle* serializer and a context-managed lifecycle (the connection is always
closed after the command). The raw SQLite connection never escapes this module.
This is the LangGraph checkpoint serializer layer — it is distinct from, and used
in addition to, the JSON-safe GraphState validation in ``workflows.state``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver

from ant_orchestrator.errors import AntError


class CheckpointStorageError(AntError):
    """The durable checkpoint store could not be opened or accessed."""


def _safe_serializer() -> JsonPlusSerializer:
    """A serializer that never falls back to pickle (no arbitrary deserialization)."""
    return JsonPlusSerializer(pickle_fallback=False)


@contextmanager
def open_checkpointer(db_path: Path) -> Iterator[SqliteSaver]:
    """Yield a ready ``SqliteSaver`` bound to ``db_path``; always close the connection.

    ``check_same_thread=False`` is required because LangGraph performs durable writes
    on an executor thread. Dependency/storage failures are translated to
    ``CheckpointStorageError`` (no raw SQL or secrets leak out).
    """
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
    except sqlite3.Error as exc:
        raise CheckpointStorageError(f"cannot open checkpoint store at {db_path.name}") from exc
    try:
        saver = SqliteSaver(conn, serde=_safe_serializer())
        saver.setup()
        yield saver
    except sqlite3.Error as exc:
        raise CheckpointStorageError("checkpoint store access failed") from exc
    finally:
        conn.close()
