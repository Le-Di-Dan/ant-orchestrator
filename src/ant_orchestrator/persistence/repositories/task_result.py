"""SQLite TaskResult repository (Phase 8 CP4).

Persists TaskResult and its ArtifactRef list atomically. The UNIQUE constraint
on task_results.workflow_run_id is the database-level idempotency guard;
a duplicate finalization attempt raises IntegrityError, caught as ConflictError.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence

from ant_orchestrator.application.ports.database import ResultConflict
from ant_orchestrator.core.domain.task_result import (
    ArtifactKind,
    ArtifactRef,
    ArtifactState,
    FailureInfo,
    TaskResult,
    TaskResultOutcome,
)
from ant_orchestrator.core.domain.value_objects import TaskResultId, UtcTimestamp
from ant_orchestrator.persistence.repositories.base import SqliteRepository

_RESULT_COLS = (
    "id, task_id, workflow_run_id, outcome, summary, "
    "failure_code, failure_message, failure_retryable, failure_source, "
    "finalized_at, result_version"
)

_ARTIFACT_COLS = (
    "id, task_result_id, kind, relative_path, media_type, sha256, "
    "size_bytes, created_by_attempt_id, state, metadata_json, created_at"
)


def _failure_from_row(row: sqlite3.Row) -> FailureInfo | None:
    if row["failure_code"] is None:
        return None
    return FailureInfo(
        code=row["failure_code"],
        message=row["failure_message"] or "",
        retryable=bool(row["failure_retryable"]),
        source=row["failure_source"] or "",
    )


def _artifact_from_row(row: sqlite3.Row) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=row["id"],
        kind=ArtifactKind(row["kind"]),
        relative_path=row["relative_path"],
        media_type=row["media_type"],
        sha256=row["sha256"],
        size_bytes=row["size_bytes"],
        created_by_attempt_id=row["created_by_attempt_id"],
        state=ArtifactState(row["state"]),
        metadata=row["metadata_json"] or "{}",
    )


def _result_from_row(row: sqlite3.Row, artifacts: Sequence[ArtifactRef]) -> TaskResult:
    return TaskResult(
        result_id=TaskResultId(row["id"]),
        task_id=row["task_id"],
        workflow_run_id=row["workflow_run_id"],
        outcome=TaskResultOutcome(row["outcome"]),
        summary=row["summary"],
        artifact_refs=tuple(artifacts),
        failure=_failure_from_row(row),
        finalized_at=UtcTimestamp.from_iso(row["finalized_at"]),
        result_version=row["result_version"],
    )


class SqliteTaskResultRepository(SqliteRepository):
    """Append-only persistence for task results and their artifact refs."""

    def find_by_run(self, workflow_run_id: str) -> TaskResult | None:
        """Return the final TaskResult for this run, or None if not yet finalized."""
        with self._db.connect() as conn:
            row = conn.execute(
                f"SELECT {_RESULT_COLS} FROM task_results WHERE workflow_run_id = ?",
                (workflow_run_id,),
            ).fetchone()
            if row is None:
                return None
            artifacts = self._load_artifacts(conn, row["id"])
        return _result_from_row(row, artifacts)

    def find_by_task(self, task_id: str) -> TaskResult | None:
        """Return the most recently finalized TaskResult for this task, or None."""
        with self._db.connect() as conn:
            row = conn.execute(
                f"SELECT {_RESULT_COLS} FROM task_results WHERE task_id = ? "
                "ORDER BY finalized_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            artifacts = self._load_artifacts(conn, row["id"])
        return _result_from_row(row, artifacts)

    def save(self, result: TaskResult, *, artifact_created_at: str) -> None:
        """Persist result + artifact refs atomically; raise ConflictError on duplicate run."""
        failure_retryable = None
        if result.failure is not None:
            failure_retryable = 1 if result.failure.retryable else 0

        try:
            with self._db.transaction() as conn:
                conn.execute(
                    f"INSERT INTO task_results ({_RESULT_COLS}) VALUES "
                    "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.result_id.value,
                        result.task_id,
                        result.workflow_run_id,
                        result.outcome.value,
                        result.summary,
                        result.failure.code if result.failure else None,
                        result.failure.message if result.failure else None,
                        failure_retryable,
                        result.failure.source if result.failure else None,
                        result.finalized_at.to_iso(),
                        result.result_version,
                    ),
                )
                for ref in result.artifact_refs:
                    conn.execute(
                        f"INSERT INTO task_result_artifacts ({_ARTIFACT_COLS}) VALUES "
                        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            ref.artifact_id,
                            result.result_id.value,
                            ref.kind.value,
                            ref.relative_path,
                            ref.media_type,
                            ref.sha256,
                            ref.size_bytes,
                            ref.created_by_attempt_id,
                            ref.state.value,
                            ref.metadata if ref.metadata != "{}" else None,
                            artifact_created_at,
                        ),
                    )
        except sqlite3.IntegrityError as exc:
            raise ResultConflict(
                f"TaskResult for run {result.workflow_run_id!r} already exists"
            ) from exc

    def _load_artifacts(self, conn: sqlite3.Connection, result_id: str) -> list[ArtifactRef]:
        rows = conn.execute(
            f"SELECT {_ARTIFACT_COLS} FROM task_result_artifacts WHERE task_result_id = ?",
            (result_id,),
        ).fetchall()
        return [_artifact_from_row(r) for r in rows]
