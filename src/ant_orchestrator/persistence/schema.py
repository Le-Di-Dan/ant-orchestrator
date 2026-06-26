"""SQLite schema (v2 authority) — DDL and expected-structure metadata.

CHECK constraints are generated from the domain enums so the allowed values have a
single source of truth. v2 adds the Phase 4 workflow-execution tables and extends
``approvals`` (see ``schema_workflow``); ``CODE_MAX_VERSION`` is bumped to 2.
Fresh installs are created directly at v2; existing v1 files are upgraded by the
v1->v2 migration (``migration_v2``).
"""

from __future__ import annotations

from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    PheromoneType,
    TaskPriority,
    TaskSource,
    TaskStatus,
    WorkerRunStatus,
)
from ant_orchestrator.persistence.schema_common import (
    CODE_MAX_VERSION,
    MIGRATIONS_TABLE,
    check_in,
)
from ant_orchestrator.persistence.schema_workflow import (
    APPROVALS_V2_COLUMNS,
    APPROVALS_V2_DDL,
    WORKFLOW_AUX_DDL,
    WORKFLOW_EXPECTED_SCHEMA,
    WORKFLOW_INDEX_DDL,
    WORKFLOW_RUNS_DDL,
)

__all__ = [
    "CODE_MAX_VERSION",
    "EXPECTED_SCHEMA",
    "INDEX_DDL",
    "MIGRATIONS_TABLE",
    "TABLE_DDL",
]

_MIGRATIONS_DDL = f"""CREATE TABLE {MIGRATIONS_TABLE} (
    version INTEGER PRIMARY KEY NOT NULL,
    applied_at TEXT NOT NULL
)"""

_TASKS_DDL = f"""CREATE TABLE tasks (
    id TEXT PRIMARY KEY NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK ({check_in("status", TaskStatus)}),
    source TEXT NOT NULL CHECK ({check_in("source", TaskSource)}),
    priority TEXT NOT NULL CHECK ({check_in("priority", TaskPriority)}),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

_WORKER_RUNS_DDL = f"""CREATE TABLE worker_runs (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK ({check_in("status", WorkerRunStatus)}),
    started_at TEXT,
    finished_at TEXT,
    created_at TEXT NOT NULL
)"""

_ENERGY_USAGE_DDL = """CREATE TABLE energy_usage (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
    worker_run_id TEXT REFERENCES worker_runs(id) ON DELETE RESTRICT,
    tokens_in INTEGER NOT NULL CHECK (tokens_in >= 0),
    tokens_out INTEGER NOT NULL CHECK (tokens_out >= 0),
    created_at TEXT NOT NULL,
    CHECK (task_id IS NOT NULL OR worker_run_id IS NOT NULL)
)"""

_CHECKPOINTS_DDL = """CREATE TABLE workflow_checkpoints (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    payload_version INTEGER NOT NULL,
    payload_json TEXT NOT NULL,
    created_at TEXT NOT NULL
)"""

_EVIDENCE_DDL = """CREATE TABLE execution_evidence (
    id TEXT PRIMARY KEY NOT NULL,
    worker_run_id TEXT NOT NULL REFERENCES worker_runs(id) ON DELETE RESTRICT,
    files_read_json TEXT,
    files_changed_json TEXT,
    commands_json TEXT,
    result TEXT,
    created_at TEXT NOT NULL
)"""

_HANDOFF_DDL = """CREATE TABLE handoff_records (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    summary TEXT NOT NULL,
    what_changed TEXT,
    next_steps TEXT,
    created_at TEXT NOT NULL
)"""

_PHEROMONES_DDL = f"""CREATE TABLE pheromones (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT REFERENCES tasks(id) ON DELETE RESTRICT,
    type TEXT NOT NULL CHECK ({check_in("type", PheromoneType)}),
    summary TEXT NOT NULL,
    files_json TEXT,
    expires_at TEXT,
    confidence TEXT CHECK ({check_in("confidence", ConfidenceLevel, nullable=True)}),
    created_at TEXT NOT NULL
)"""

_MEMORY_DDL = f"""CREATE TABLE memory_records (
    id TEXT PRIMARY KEY NOT NULL,
    type TEXT NOT NULL CHECK ({check_in("type", MemoryType)}),
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    source TEXT,
    confidence TEXT CHECK ({check_in("confidence", ConfidenceLevel, nullable=True)}),
    tags_json TEXT,
    created_at TEXT NOT NULL,
    deprecated INTEGER NOT NULL DEFAULT 0 CHECK (deprecated IN (0, 1))
)"""

# Ordered so every FK target is created before its referrer (workflow_runs before
# approvals; approvals before resume_operations).
TABLE_DDL: tuple[str, ...] = (
    _MIGRATIONS_DDL,
    _TASKS_DDL,
    WORKFLOW_RUNS_DDL,
    _WORKER_RUNS_DDL,
    _ENERGY_USAGE_DDL,
    _CHECKPOINTS_DDL,
    APPROVALS_V2_DDL,
    _EVIDENCE_DDL,
    _HANDOFF_DDL,
    _PHEROMONES_DDL,
    _MEMORY_DDL,
    *WORKFLOW_AUX_DDL,
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

INDEX_DDL: tuple[str, ...] = (*_V1_INDEX_DDL, *WORKFLOW_INDEX_DDL)

_APPROVALS_EXPECTED = (
    frozenset({"id", "task_id", "checkpoint_id", "status", "reason", "requested_at", "decided_at"})
    | APPROVALS_V2_COLUMNS
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
    "approvals": _APPROVALS_EXPECTED,
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
    **WORKFLOW_EXPECTED_SCHEMA,
}
