"""Cross-process evidence readers for the CP8 restart E2E suite (test-only).

Every helper opens a *fresh* connection (or a fresh checkpointer) against the
workspace databases — nothing relies on an object still alive in an earlier
process. Business state is read from ``.ant/state.sqlite``; resume-not-rerun
evidence is read from the LangGraph checkpoint history (no log grepping).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ant_orchestrator.application.services.workflow_support import thread_id_for
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.workflows.checkpointer import open_checkpointer
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.graph import build_workflow_graph
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    CHECKPOINT_DB_FILENAME,
    DATABASE_FILENAME,
)


def state_db_path(workspace: Path) -> Path:
    """Absolute path to the business-state SQLite file."""
    return workspace / ANT_DIRNAME / DATABASE_FILENAME


def checkpoint_db_path(workspace: Path) -> Path:
    """Absolute path to the LangGraph checkpoint SQLite file."""
    return workspace / ANT_DIRNAME / CHECKPOINT_DB_FILENAME


def _connect(workspace: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(state_db_path(workspace)))
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Business-state readers (fresh connection each call)
# ---------------------------------------------------------------------------


def count_rows(workspace: Path, table: str) -> int:
    """Row count of ``table`` in the business-state database."""
    with _connect(workspace) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def fetch_rows(workspace: Path, table: str, order_by: str = "") -> list[sqlite3.Row]:
    """All rows of ``table`` (optionally ordered) as a fresh-connection snapshot."""
    suffix = f" ORDER BY {order_by}" if order_by else ""
    with _connect(workspace) as conn:
        return list(conn.execute(f"SELECT * FROM {table}{suffix}").fetchall())


def execution_attempts(workspace: Path) -> list[sqlite3.Row]:
    """All execution attempts ordered by ``attempt_no``."""
    return fetch_rows(workspace, "execution_attempts", "attempt_no")


def approvals(workspace: Path) -> list[sqlite3.Row]:
    """All approval rows."""
    return fetch_rows(workspace, "approvals")


def resume_operations(workspace: Path) -> list[sqlite3.Row]:
    """All resume-operation rows."""
    return fetch_rows(workspace, "resume_operations")


def transitions(workspace: Path, *, trigger: str | None = None) -> list[sqlite3.Row]:
    """Append-only status transitions, optionally filtered by ``trigger``."""
    rows = fetch_rows(workspace, "status_transitions")
    if trigger is None:
        return rows
    return [r for r in rows if r["trigger"] == trigger]


def task_row(workspace: Path, task_id: str) -> sqlite3.Row | None:
    """The task row for ``task_id`` (or ``None``)."""
    with _connect(workspace) as conn:
        return conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()


def task_status(workspace: Path, task_id: str) -> str | None:
    """Current status string of ``task_id``."""
    row = task_row(workspace, task_id)
    return None if row is None else str(row["status"])


def run_row(workspace: Path, run_id: str) -> sqlite3.Row | None:
    """The workflow-run row for ``run_id`` (or ``None``)."""
    with _connect(workspace) as conn:
        return conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()


def run_status(workspace: Path, run_id: str) -> str | None:
    """Current status string of the workflow run ``run_id``."""
    row = run_row(workspace, run_id)
    return None if row is None else str(row["status"])


def succeeded_attempt_count(workspace: Path) -> int:
    """Number of execution attempts in the SUCCEEDED terminal state."""
    return sum(1 for r in execution_attempts(workspace) if r["status"] == "succeeded")


# ---------------------------------------------------------------------------
# Database separation (schema isolation between the two SQLite files)
# ---------------------------------------------------------------------------


def _table_names(path: Path) -> set[str]:
    with sqlite3.connect(str(path)) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    return {str(r[0]) for r in rows}


def state_tables(workspace: Path) -> set[str]:
    """Table names present in the business-state database."""
    return _table_names(state_db_path(workspace))


def checkpoint_tables(workspace: Path) -> set[str]:
    """Table names present in the LangGraph checkpoint database."""
    return _table_names(checkpoint_db_path(workspace))


# ---------------------------------------------------------------------------
# Checkpoint history (resume-not-rerun evidence, no log grep)
# ---------------------------------------------------------------------------


class _NullWorker:
    """A worker that must never be invoked (history reads don't execute nodes)."""

    def execute(self, intent: object) -> Any:  # pragma: no cover - defensive
        raise AssertionError("history read must not invoke the worker")


def _read_only_graph(workspace: Path) -> Any:
    saver_cm = open_checkpointer(checkpoint_db_path(workspace))
    policy = DecisionGatePolicy(EnforcementPolicy())
    return saver_cm, build_workflow_graph(_NullWorker(), policy)


def node_schedule_counts(workspace: Path, run_id: str) -> dict[str, int]:
    """Count how many durable checkpoints queued each node to run next (== runs).

    Reads ``get_state_history`` directly from the durable checkpoint DB via a fresh
    checkpointer (no log grep). Every super-step writes a checkpoint whose ``next``
    names the node that runs from it; a node that ran once before an interrupt and
    is not re-run on resume keeps a count of 1 — the core resume-not-rerun signal.
    """
    config = {"configurable": {"thread_id": thread_id_for(run_id)}}
    counts: dict[str, int] = {}
    saver_cm, graph = _read_only_graph(workspace)
    with saver_cm as saver:
        app = graph.compile(checkpointer=saver)
        for snapshot in app.get_state_history(config):
            for node in snapshot.next:
                counts[str(node)] = counts.get(str(node), 0) + 1
    return counts


def latest_state_values(workspace: Path, run_id: str) -> dict[str, Any]:
    """The latest durable graph-state values for ``run_id`` (fresh checkpointer)."""
    config = {"configurable": {"thread_id": thread_id_for(run_id)}}
    saver_cm, graph = _read_only_graph(workspace)
    with saver_cm as saver:
        app = graph.compile(checkpointer=saver)
        return dict(app.get_state(config).values)


def checkpoint_count(workspace: Path, run_id: str) -> int:
    """Number of durable checkpoints recorded for ``run_id``'s thread."""
    config = {"configurable": {"thread_id": thread_id_for(run_id)}}
    saver_cm, graph = _read_only_graph(workspace)
    with saver_cm as saver:
        app = graph.compile(checkpointer=saver)
        return sum(1 for _ in app.get_state_history(config))
