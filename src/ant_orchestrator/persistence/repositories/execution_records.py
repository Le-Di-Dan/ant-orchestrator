"""Connection-bound execution-record repositories (PHASE_5_PLAN CP6).

The Phase-1 ``Sqlite*Repository`` variants each open their own transaction, so they
cannot persist atomically with the rest of a unit of work. CP6 needs WorkerRun,
ExecutionEvidence and the durable energy-settlement row to commit in ONE transaction
(I11 ordering), so these variants bind to the unit of work's shared connection and never
commit on their own. Each exposes ``find`` (returns ``None`` when absent) so the caller
can run compare-and-verify reconciliation instead of a silent overwrite: a deterministic
primary key makes a retry an idempotent no-op and a different authority a hard conflict.
"""

from __future__ import annotations

import sqlite3

from ant_orchestrator.core.domain.entities import WorkerRun
from ant_orchestrator.core.domain.enums import WorkerRunStatus
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.persistence.repositories.base import ConnRepository
from ant_orchestrator.persistence.serialization import (
    dump_str_tuple,
    iso_or_none,
    load_str_tuple,
    parse_iso_or_none,
)

_WR_COLUMNS = "id, task_id, status, started_at, finished_at, created_at"
_EV_COLUMNS = (
    "id, worker_run_id, files_read_json, files_changed_json, commands_json, result, created_at"
)
_EU_COLUMNS = "id, task_id, worker_run_id, tokens_in, tokens_out, created_at"


class ConnWorkerRunRepository(ConnRepository):
    """WorkerRun persistence bound to a unit-of-work connection."""

    def find(self, worker_run_id: WorkerRunId) -> WorkerRun | None:
        row = self._conn.execute(
            "SELECT * FROM worker_runs WHERE id = ?", (worker_run_id.value,)
        ).fetchone()
        return _to_worker_run(row) if row is not None else None

    def add(self, worker_run: WorkerRun) -> None:
        self._conn.execute(
            f"INSERT INTO worker_runs ({_WR_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                worker_run.id.value,
                worker_run.task_id.value,
                worker_run.status.value,
                iso_or_none(worker_run.started_at),
                iso_or_none(worker_run.finished_at),
                worker_run.created_at.to_iso(),
            ),
        )


class ConnExecutionEvidenceRepository(ConnRepository):
    """ExecutionEvidence persistence bound to a unit-of-work connection."""

    def find(self, evidence_id: EvidenceId) -> ExecutionEvidence | None:
        row = self._conn.execute(
            "SELECT * FROM execution_evidence WHERE id = ?", (evidence_id.value,)
        ).fetchone()
        return _to_evidence(row) if row is not None else None

    def add(self, evidence: ExecutionEvidence) -> None:
        self._conn.execute(
            f"INSERT INTO execution_evidence ({_EV_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                evidence.id.value,
                evidence.worker_run_id.value,
                dump_str_tuple(evidence.files_read),
                dump_str_tuple(evidence.files_changed),
                dump_str_tuple(evidence.commands),
                evidence.result,
                evidence.created_at.to_iso(),
            ),
        )


class ConnEnergyUsageRepository(ConnRepository):
    """EnergyUsage (durable settlement) persistence bound to a unit-of-work connection."""

    def find(self, usage_id: EnergyUsageId) -> EnergyUsage | None:
        row = self._conn.execute(
            "SELECT * FROM energy_usage WHERE id = ?", (usage_id.value,)
        ).fetchone()
        return _to_energy_usage(row) if row is not None else None

    def add(self, usage: EnergyUsage) -> None:
        self._conn.execute(
            f"INSERT INTO energy_usage ({_EU_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?)",
            (
                usage.id.value,
                usage.task_id.value if usage.task_id is not None else None,
                usage.worker_run_id.value if usage.worker_run_id is not None else None,
                usage.tokens_in.value,
                usage.tokens_out.value,
                usage.created_at.to_iso(),
            ),
        )


def _to_worker_run(row: sqlite3.Row) -> WorkerRun:
    return WorkerRun(
        id=WorkerRunId(row["id"]),
        task_id=TaskId(row["task_id"]),
        status=WorkerRunStatus.parse(row["status"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        started_at=parse_iso_or_none(row["started_at"]),
        finished_at=parse_iso_or_none(row["finished_at"]),
    )


def _to_evidence(row: sqlite3.Row) -> ExecutionEvidence:
    return ExecutionEvidence(
        id=EvidenceId(row["id"]),
        worker_run_id=WorkerRunId(row["worker_run_id"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        files_read=load_str_tuple(row["files_read_json"]),
        files_changed=load_str_tuple(row["files_changed_json"]),
        commands=load_str_tuple(row["commands_json"]),
        result=row["result"],
    )


def _to_energy_usage(row: sqlite3.Row) -> EnergyUsage:
    task_id = row["task_id"]
    worker_run_id = row["worker_run_id"]
    return EnergyUsage(
        id=EnergyUsageId(row["id"]),
        tokens_in=TokenCount(row["tokens_in"]),
        tokens_out=TokenCount(row["tokens_out"]),
        created_at=UtcTimestamp.from_iso(row["created_at"]),
        task_id=TaskId(task_id) if task_id is not None else None,
        worker_run_id=WorkerRunId(worker_run_id) if worker_run_id is not None else None,
    )
