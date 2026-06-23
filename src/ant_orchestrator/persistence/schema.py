"""SQLite schema v1 DDL and expected-structure metadata (PHASE_1_PLAN §13.1).

CHECK constraints are generated from the domain enums so the allowed values have a
single source of truth.
"""

from __future__ import annotations

from enum import Enum

from ant_orchestrator.core.domain.enums import (
    ApprovalStatus,
    ConfidenceLevel,
    MemoryType,
    PheromoneType,
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)

CODE_MAX_VERSION = 1
MIGRATIONS_TABLE = "schema_migrations"


def _values(enum_cls: type[Enum]) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_cls.__members__.values())


def _check_in(column: str, enum_cls: type[Enum], *, nullable: bool = False) -> str:
    clause = f"{column} IN ({_values(enum_cls)})"
    return f"({column} IS NULL OR {clause})" if nullable else clause


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE {MIGRATIONS_TABLE} (
        version INTEGER PRIMARY KEY NOT NULL,
        applied_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE tasks (
        id TEXT PRIMARY KEY NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL CHECK ({_check_in("status", TaskStatus)}),
        source TEXT NOT NULL CHECK ({_check_in("source", TaskSource)}),
        priority TEXT NOT NULL CHECK ({_check_in("priority", TaskPriority)}),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE worker_runs (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK ({_check_in("status", WorkerRunStatus)}),
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
    f"""CREATE TABLE approvals (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
        checkpoint_id TEXT REFERENCES workflow_checkpoints(id) ON DELETE RESTRICT,
        status TEXT NOT NULL CHECK ({_check_in("status", ApprovalStatus)}),
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
    f"""CREATE TABLE pheromones (
        id TEXT PRIMARY KEY NOT NULL,
        task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
        type TEXT NOT NULL CHECK ({_check_in("type", PheromoneType)}),
        summary TEXT NOT NULL,
        files_json TEXT,
        expires_at TEXT,
        confidence TEXT CHECK ({_check_in("confidence", ConfidenceLevel, nullable=True)}),
        created_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE memory_records (
        id TEXT PRIMARY KEY NOT NULL,
        type TEXT NOT NULL CHECK ({_check_in("type", MemoryType)}),
        title TEXT NOT NULL,
        summary TEXT NOT NULL,
        source TEXT,
        confidence TEXT CHECK ({_check_in("confidence", ConfidenceLevel, nullable=True)}),
        tags_json TEXT,
        created_at TEXT NOT NULL,
        deprecated INTEGER NOT NULL DEFAULT 0 CHECK (deprecated IN (0, 1))
    )""",
)

INDEX_DDL: tuple[str, ...] = (
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

# Expected tables -> required columns, used to verify integrity (Patch7).
EXPECTED_SCHEMA: dict[str, frozenset[str]] = {
    MIGRATIONS_TABLE: frozenset({"version", "applied_at"}),
    "tasks": frozenset({"id", "title", "status", "source", "priority", "created_at", "updated_at"}),
    "worker_runs": frozenset(
        {"id", "task_id", "status", "started_at", "finished_at", "created_at"}
    ),
    "energy_usage": frozenset(
        {"id", "task_id", "worker_run_id", "tokens_in", "tokens_out", "created_at"}
    ),
    "workflow_checkpoints": frozenset(
        {"id", "task_id", "payload_version", "payload_json", "created_at"}
    ),
    "approvals": frozenset(
        {"id", "task_id", "checkpoint_id", "status", "reason", "requested_at", "decided_at"}
    ),
    "execution_evidence": frozenset(
        {
            "id",
            "worker_run_id",
            "files_read_json",
            "files_changed_json",
            "commands_json",
            "result",
            "created_at",
        }
    ),
    "handoff_records": frozenset(
        {"id", "task_id", "summary", "what_changed", "next_steps", "created_at"}
    ),
    "pheromones": frozenset(
        {"id", "task_id", "type", "summary", "files_json", "expires_at", "confidence", "created_at"}
    ),
    "memory_records": frozenset(
        {
            "id",
            "type",
            "title",
            "summary",
            "source",
            "confidence",
            "tags_json",
            "created_at",
            "deprecated",
        }
    ),
}
