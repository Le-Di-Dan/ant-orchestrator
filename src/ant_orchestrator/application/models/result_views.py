"""Read-model DTOs for task result presentation (Phase 8 CP4)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FailureInfoView:
    """Sanitized failure details for presentation."""

    code: str
    message: str
    retryable: bool
    source: str


@dataclass(frozen=True, slots=True)
class ArtifactRefView:
    """Read-model for a single artifact reference."""

    artifact_id: str
    kind: str
    relative_path: str
    media_type: str
    sha256: str
    size_bytes: int
    created_by_attempt_id: str | None
    state: str
    metadata: str


@dataclass(frozen=True, slots=True)
class TaskResultView:
    """Full read-model for a finalized task result."""

    result_id: str
    task_id: str
    workflow_run_id: str
    outcome: str
    summary: str
    artifact_refs: tuple[ArtifactRefView, ...]
    failure: FailureInfoView | None
    finalized_at: str
    result_version: int
