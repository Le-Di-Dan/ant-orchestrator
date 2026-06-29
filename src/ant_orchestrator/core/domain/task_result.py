"""TaskResult, ArtifactRef, and FailureInfo domain value objects (Phase 8 CP4).

Contract invariants:
- A TaskResult is immutable once finalized; its result_id is deterministic.
- ArtifactRef.relative_path is validated against path-safety rules before construction.
- FailureInfo contains only sanitized, bounded strings (no traceback, no secret).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Final

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TaskResultId, UtcTimestamp

__all__ = [
    "ArtifactKind",
    "ArtifactRef",
    "ArtifactState",
    "FailureInfo",
    "TaskResult",
    "TaskResultOutcome",
    "make_result_id",
]

_ID_SEP: Final = "\x00"
_HEX_CHARS: Final = frozenset("0123456789abcdef")

# Domain-internal validation bounds (mirrors config.constants; kept here for layer purity).
_SHA256_HEX_LEN: Final = 64
_MAX_MEDIA_TYPE: Final = 128
_MAX_METADATA_BYTES: Final = 4096
_MAX_PATH: Final = 512
_MAX_CODE: Final = 80
_MAX_MSG: Final = 500
_MAX_SOURCE: Final = 80
_MAX_SUMMARY: Final = 2000
_RESULT_VERSION: Final = 1


class TaskResultOutcome(Enum):
    """Terminal business outcome of a workflow run."""

    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class ArtifactKind(Enum):
    """Storage location tier of a persisted artifact."""

    INTERNAL = "internal"
    STAGED = "staged"
    APPLIED = "applied"


class ArtifactState(Enum):
    """Lifecycle state of a persisted artifact."""

    PENDING = "pending"
    FINAL = "final"
    REJECTED = "rejected"


def make_result_id(workflow_run_id: str, outcome: str) -> TaskResultId:
    """Deterministic TaskResultId from run identity and outcome string."""
    seed = _ID_SEP.join(("task_result", workflow_run_id, outcome))
    return TaskResultId(hashlib.sha256(seed.encode("utf-8")).hexdigest())


@dataclass(frozen=True, slots=True)
class FailureInfo:
    """Sanitized, bounded failure details — no traceback, exception, or secret."""

    code: str
    message: str
    retryable: bool
    source: str

    def __post_init__(self) -> None:
        if not self.code or len(self.code) > _MAX_CODE:
            raise InvariantViolation(f"FailureInfo.code must be 1-{_MAX_CODE} chars")
        if len(self.message) > _MAX_MSG:
            raise InvariantViolation(f"FailureInfo.message exceeds {_MAX_MSG} chars")
        if len(self.source) > _MAX_SOURCE:
            raise InvariantViolation(f"FailureInfo.source exceeds {_MAX_SOURCE} chars")

    @classmethod
    def for_outcome(
        cls,
        outcome: str,
        *,
        reason: str | None = None,
        retryable: bool = False,
        source: str = "workflow",
    ) -> FailureInfo:
        """Build a sanitized FailureInfo from an outcome string and optional reason."""
        code = outcome[:_MAX_CODE] if outcome else "unknown"
        msg = (reason or outcome)[:_MAX_MSG]
        return cls(code=code, message=msg, retryable=retryable, source=source[:_MAX_SOURCE])


def _validate_artifact_path(path: str) -> None:
    """Reject unsafe paths: empty, null-byte, absolute, UNC, traversal, Windows drive."""
    if not path:
        raise InvariantViolation("ArtifactRef.relative_path must be non-empty")
    if len(path) > _MAX_PATH:
        raise InvariantViolation(f"ArtifactRef.relative_path exceeds {_MAX_PATH} chars")
    if "\x00" in path:
        raise InvariantViolation("ArtifactRef.relative_path contains null byte")
    if path.startswith("/"):
        raise InvariantViolation("ArtifactRef.relative_path must not be absolute")
    if len(path) >= 2 and path[1] == ":":
        raise InvariantViolation("ArtifactRef.relative_path must not be an absolute Windows path")
    if path.startswith("\\\\"):
        raise InvariantViolation("ArtifactRef.relative_path must not be a UNC path")
    normalized = path.replace("\\", "/")
    for part in normalized.split("/"):
        if part == "..":
            raise InvariantViolation("ArtifactRef.relative_path must not contain '..' components")


def _validate_sha256(digest: str) -> None:
    if len(digest) != _SHA256_HEX_LEN:
        raise InvariantViolation(f"ArtifactRef.sha256 must be {_SHA256_HEX_LEN} hex chars")
    if not all(c in _HEX_CHARS for c in digest):
        raise InvariantViolation("ArtifactRef.sha256 must be lowercase hex")


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Immutable reference to a persisted artifact with digest and path invariants."""

    artifact_id: str
    kind: ArtifactKind
    relative_path: str
    media_type: str
    sha256: str
    size_bytes: int
    created_by_attempt_id: str | None
    state: ArtifactState
    metadata: str

    def __post_init__(self) -> None:
        if not self.artifact_id:
            raise InvariantViolation("ArtifactRef.artifact_id must be non-empty")
        _validate_artifact_path(self.relative_path)
        _validate_sha256(self.sha256)
        if self.size_bytes < 0:
            raise InvariantViolation("ArtifactRef.size_bytes must be >= 0")
        if len(self.media_type) > _MAX_MEDIA_TYPE:
            raise InvariantViolation(f"ArtifactRef.media_type exceeds {_MAX_MEDIA_TYPE} chars")
        if len(self.metadata.encode("utf-8")) > _MAX_METADATA_BYTES:
            raise InvariantViolation(f"ArtifactRef.metadata exceeds {_MAX_METADATA_BYTES} bytes")


@dataclass(frozen=True, slots=True)
class TaskResult:
    """Immutable finalized business result for a workflow run (one per WorkflowRun)."""

    result_id: TaskResultId
    task_id: str
    workflow_run_id: str
    outcome: TaskResultOutcome
    summary: str
    artifact_refs: tuple[ArtifactRef, ...]
    failure: FailureInfo | None
    finalized_at: UtcTimestamp
    result_version: int

    def __post_init__(self) -> None:
        if not self.task_id:
            raise InvariantViolation("TaskResult.task_id must be non-empty")
        if not self.workflow_run_id:
            raise InvariantViolation("TaskResult.workflow_run_id must be non-empty")
        if len(self.summary) > _MAX_SUMMARY:
            raise InvariantViolation(f"TaskResult.summary exceeds {_MAX_SUMMARY} chars")
        if self.result_version != _RESULT_VERSION:
            raise InvariantViolation(f"TaskResult.result_version must be {_RESULT_VERSION}")
