"""CP4 domain contract tests: TaskResult, ArtifactRef, FailureInfo value objects.

Covers:
- Valid construction for all 4 outcomes.
- Invariant violations: empty/oversized fields.
- ArtifactRef path safety: traversal, absolute, UNC, Windows drive, null byte.
- FailureInfo bounds and for_outcome factory.
- make_result_id determinism.
- TaskResult immutability (frozen dataclass).
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from ant_orchestrator.config.constants import (
    ARTIFACT_SHA256_HEX_LENGTH,
    MAX_ARTIFACT_PATH_CHARS,
    MAX_TASK_RESULT_SUMMARY_CHARS,
    TASK_RESULT_VERSION,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.task_result import (
    ArtifactKind,
    ArtifactRef,
    ArtifactState,
    FailureInfo,
    TaskResult,
    TaskResultOutcome,
    make_result_id,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp

_TS = UtcTimestamp(datetime(2026, 6, 29, tzinfo=UTC))
_DIGEST = "a" * ARTIFACT_SHA256_HEX_LENGTH


def _make_artifact(**kw: object) -> ArtifactRef:
    defaults: dict[str, object] = dict(
        artifact_id="art-001",
        kind=ArtifactKind.INTERNAL,
        relative_path="results/output.json",
        media_type="application/json",
        sha256=_DIGEST,
        size_bytes=42,
        created_by_attempt_id=None,
        state=ArtifactState.FINAL,
        metadata="{}",
    )
    defaults.update(kw)
    return ArtifactRef(**defaults)  # type: ignore[arg-type]


def _make_result(
    outcome: TaskResultOutcome = TaskResultOutcome.COMPLETED, **kw: object
) -> TaskResult:
    run_id = "run-abc"
    result_id = make_result_id(run_id, outcome.value)
    failure = (
        None if outcome is TaskResultOutcome.COMPLETED else FailureInfo.for_outcome(outcome.value)
    )
    defaults: dict[str, object] = dict(
        result_id=result_id,
        task_id="task-001",
        workflow_run_id=run_id,
        outcome=outcome,
        summary="All good.",
        artifact_refs=(),
        failure=failure,
        finalized_at=_TS,
        result_version=TASK_RESULT_VERSION,
    )
    defaults.update(kw)
    return TaskResult(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# make_result_id
# ---------------------------------------------------------------------------


def test_make_result_id_deterministic() -> None:
    id1 = make_result_id("run-xyz", "completed")
    id2 = make_result_id("run-xyz", "completed")
    assert id1.value == id2.value


def test_make_result_id_different_outcome() -> None:
    id1 = make_result_id("run-xyz", "completed")
    id2 = make_result_id("run-xyz", "failed")
    assert id1.value != id2.value


def test_make_result_id_different_run() -> None:
    id1 = make_result_id("run-aaa", "completed")
    id2 = make_result_id("run-bbb", "completed")
    assert id1.value != id2.value


# ---------------------------------------------------------------------------
# FailureInfo
# ---------------------------------------------------------------------------


def test_failure_info_valid() -> None:
    f = FailureInfo(
        code="failed", message="something went wrong", retryable=False, source="workflow"
    )
    assert f.code == "failed"
    assert not f.retryable


def test_failure_info_for_outcome_factory() -> None:
    f = FailureInfo.for_outcome("failed", reason="timeout", retryable=True, source="test")
    assert f.code == "failed"
    assert "timeout" in f.message
    assert f.retryable


def test_failure_info_empty_code_raises() -> None:
    with pytest.raises(InvariantViolation):
        FailureInfo(code="", message="x", retryable=False, source="w")


def test_failure_info_oversized_code_raises() -> None:
    with pytest.raises(InvariantViolation):
        FailureInfo(code="x" * 81, message="x", retryable=False, source="w")


def test_failure_info_oversized_message_raises() -> None:
    with pytest.raises(InvariantViolation):
        FailureInfo(code="failed", message="x" * 501, retryable=False, source="w")


def test_failure_info_oversized_source_raises() -> None:
    with pytest.raises(InvariantViolation):
        FailureInfo(code="failed", message="x", retryable=False, source="s" * 81)


# ---------------------------------------------------------------------------
# ArtifactRef — valid construction
# ---------------------------------------------------------------------------


def test_artifact_ref_valid() -> None:
    ref = _make_artifact()
    assert ref.artifact_id == "art-001"
    assert ref.sha256 == _DIGEST


def test_artifact_ref_kinds() -> None:
    for kind in ArtifactKind:
        ref = _make_artifact(kind=kind)
        assert ref.kind is kind


def test_artifact_ref_states() -> None:
    for state in ArtifactState:
        ref = _make_artifact(state=state)
        assert ref.state is state


# ---------------------------------------------------------------------------
# ArtifactRef — path safety
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_path",
    [
        "",
        "../escape",
        "subdir/../../escape",
        "/absolute/posix",
        "C:\\Windows\\system32",
        "C:/windows/system32",
        "\\\\server\\share",
        "path\x00null",
        "x" * (MAX_ARTIFACT_PATH_CHARS + 1),
    ],
)
def test_artifact_ref_unsafe_path_raises(bad_path: str) -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(relative_path=bad_path)


@pytest.mark.parametrize(
    "good_path",
    [
        "results/output.json",
        "output.txt",
        "a/b/c/d.bin",
        "with spaces/file.md",
        "unicode_ñ/file.txt",
    ],
)
def test_artifact_ref_safe_paths_accepted(good_path: str) -> None:
    ref = _make_artifact(relative_path=good_path)
    assert ref.relative_path == good_path


def test_artifact_ref_empty_id_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(artifact_id="")


def test_artifact_ref_invalid_sha256_length() -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(sha256="abc123")


def test_artifact_ref_uppercase_sha256_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(sha256="A" * ARTIFACT_SHA256_HEX_LENGTH)


def test_artifact_ref_negative_size_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(size_bytes=-1)


def test_artifact_ref_oversized_metadata_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_artifact(metadata="x" * 5000)


# ---------------------------------------------------------------------------
# TaskResult
# ---------------------------------------------------------------------------


def test_task_result_completed_valid() -> None:
    r = _make_result(TaskResultOutcome.COMPLETED)
    assert r.outcome is TaskResultOutcome.COMPLETED
    assert r.failure is None


def test_task_result_failed_valid() -> None:
    r = _make_result(TaskResultOutcome.FAILED)
    assert r.outcome is TaskResultOutcome.FAILED
    assert r.failure is not None


def test_task_result_rejected_valid() -> None:
    r = _make_result(TaskResultOutcome.REJECTED)
    assert r.outcome is TaskResultOutcome.REJECTED


def test_task_result_cancelled_valid() -> None:
    r = _make_result(TaskResultOutcome.CANCELLED)
    assert r.outcome is TaskResultOutcome.CANCELLED


def test_task_result_oversized_summary_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_result(summary="x" * (MAX_TASK_RESULT_SUMMARY_CHARS + 1))


def test_task_result_empty_task_id_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_result(task_id="")


def test_task_result_empty_run_id_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_result(workflow_run_id="")


def test_task_result_wrong_version_raises() -> None:
    with pytest.raises(InvariantViolation):
        _make_result(result_version=99)


def test_task_result_immutable() -> None:
    r = _make_result()
    with pytest.raises((AttributeError, TypeError, dataclasses.FrozenInstanceError)):
        r.summary = "mutated"  # type: ignore[misc]


def test_task_result_with_artifacts() -> None:
    art = _make_artifact()
    r = _make_result(artifact_refs=(art,))
    assert len(r.artifact_refs) == 1
    assert r.artifact_refs[0].artifact_id == "art-001"
