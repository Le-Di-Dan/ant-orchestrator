"""Frozen snapshot of the pre-Phase-4 (v1) SQLite schema (test-only).

Used to build a genuine v1 database file so the v1->v2 migration can be exercised
end to end. This is intentionally a literal snapshot — it must NOT track the live
``schema`` module, which now describes v2.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

_V1_TABLE_DDL: tuple[str, ...] = (
    """CREATE TABLE schema_migrations (
        version INTEGER PRIMARY KEY NOT NULL,
        applied_at TEXT NOT NULL
    )""",
    """CREATE TABLE tasks (
        id TEXT PRIMARY KEY NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('created', 'classified', 'planned', 'split',
            'assigned', 'running', 'validating', 'reviewing', 'waiting_for_approval',
            'blocked', 'completed', 'failed', 'cancelled', 'rejected')),
        source TEXT NOT NULL CHECK (source IN ('human', 'cli', 'api')),
        priority TEXT NOT NULL CHECK (priority IN ('low', 'normal', 'high')),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE worker_runs (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK (status IN ('pending', 'running', 'succeeded',
            'failed', 'cancelled')),
        started_at TEXT,
        finished_at TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE energy_usage (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
        worker_run_id TEXT REFERENCES worker_runs(id) ON DELETE RESTRICT,
        tokens_in INTEGER NOT NULL CHECK (tokens_in >= 0),
        tokens_out INTEGER NOT NULL CHECK (tokens_out >= 0),
        created_at TEXT NOT NULL,
        CHECK (task_id IS NOT NULL OR worker_run_id IS NOT NULL)
    )""",
    """CREATE TABLE workflow_checkpoints (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        payload_version INTEGER NOT NULL,
        payload_json TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE approvals (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        checkpoint_id TEXT REFERENCES workflow_checkpoints(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
        reason TEXT,
        requested_at TEXT NOT NULL,
        decided_at TEXT,
        CHECK (
            (status = 'pending' AND decided_at IS NULL)
            OR (status IN ('approved', 'rejected') AND decided_at IS NOT NULL)
        )
    )""",
    """CREATE TABLE execution_evidence (
        id TEXT PRIMARY KEY NOT NULL,
        worker_run_id TEXT NOT NULL REFERENCES worker_runs(id) ON DELETE RESTRICT,
        files_read_json TEXT,
        files_changed_json TEXT,
        commands_json TEXT,
        result TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE handoff_records (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        summary TEXT NOT NULL,
        what_changed TEXT,
        next_steps TEXT,
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE pheromones (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
        type TEXT NOT NULL CHECK (type IN ('file_relevance', 'test_failure', 'worker_note',
            'risk_signal', 'next_step', 'blocked_reason', 'context_hint')),
        summary TEXT NOT NULL,
        files_json TEXT,
        expires_at TEXT,
        confidence TEXT CHECK (confidence IS NULL OR confidence IN ('low', 'medium', 'high')),
        created_at TEXT NOT NULL
    )""",
    """CREATE TABLE memory_records (
        id TEXT PRIMARY KEY NOT NULL,
        type TEXT NOT NULL CHECK (type IN ('project_fact', 'technical_decision',
            'coding_convention', 'architecture_summary', 'known_issue', 'successful_pattern',
            'human_preference', 'risk_note')),
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        source TEXT,
        confidence TEXT CHECK (confidence IS NULL OR confidence IN ('low', 'medium', 'high')),
        tags_json TEXT,
        created_at TEXT NOT NULL,
        deprecated INTEGER NOT NULL DEFAULT 0 CHECK (deprecated IN (0, 1))
    )""",
)

_V1_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX idx_tasks_status ON tasks(status)",
    "CREATE INDEX idx_wr_task ON worker_runs(task_id)",
    "CREATE INDEX idx_energy_task ON energy_usage(task_id)",
    "CREATE INDEX idx_energy_run ON energy_usage(worker_run_id)",
    "CREATE INDEX idx_ckpt_task ON workflow_checkpoints(task_id, created_at)",
    "CREATE INDEX idx_appr_task ON approvals(task_id)",
    "CREATE INDEX idx_evi_run ON execution_evidence(worker_run_id)",
    "CREATE INDEX idx_handoff_task ON handoff_records(task_id)",
    "CREATE INDEX idx_pher_task ON pheromones(task_id)",
    "CREATE INDEX idx_mem_type ON memory_records(type)",
)


def build_v1_database(db_path: Path, *, applied_at: str = "2026-06-20T00:00:00+00:00") -> None:
    """Create a fresh, complete v1 database file at ``db_path``."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for ddl in _V1_TABLE_DDL:
            conn.execute(ddl)
        for ddl in _V1_INDEX_DDL:
            conn.execute(ddl)
        conn.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (1, ?)", (applied_at,)
        )
        conn.commit()
    finally:
        conn.close()
