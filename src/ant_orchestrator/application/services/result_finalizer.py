"""TaskResultFinalizer — persist terminal workflow outcome as TaskResult (CP4).

Called as Phase 3 in CompletionFinalizer after Phase 1 (CAS status) and Phase 2
(terminal handoff). The result_id is deterministic so replay after a crash is
idempotent: find existing → return without error.

The finalizer extracts a bounded, sanitized summary from graph state; it never
persists raw provider output, tracebacks, secrets, or absolute host paths.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Protocol, runtime_checkable

from ant_orchestrator.application.ports.database import ResultConflict
from ant_orchestrator.config.constants import (
    MAX_TASK_RESULT_SUMMARY_CHARS,
    TASK_RESULT_VERSION,
)
from ant_orchestrator.core.domain.task_result import (
    ArtifactRef,
    FailureInfo,
    TaskResult,
    TaskResultOutcome,
    make_result_id,
)
from ant_orchestrator.core.ports.clock import Clock

__all__ = ["ResultArtifactProvider", "TaskResultFinalizer", "TaskResultWriteRepository"]

_SUMMARY_FALLBACK: Final = "Workflow completed; no summary available."

_OUTCOME_MAP: Final[dict[str, TaskResultOutcome]] = {
    "completed": TaskResultOutcome.COMPLETED,
    "failed": TaskResultOutcome.FAILED,
    "rejected": TaskResultOutcome.REJECTED,
    "cancelled": TaskResultOutcome.CANCELLED,
}


@runtime_checkable
class TaskResultWriteRepository(Protocol):
    """Minimal write port for task result finalization (application-layer view)."""

    def find_by_run(self, workflow_run_id: str) -> TaskResult | None: ...

    def save(self, result: TaskResult, *, artifact_created_at: str) -> None: ...


@runtime_checkable
class ResultArtifactProvider(Protocol):
    """Optional hook that materializes artifacts to persist with a TaskResult.

    Production ``run`` leaves this unset, so the finalizer persists no artifacts and
    behaviour is unchanged. The deterministic self-test injects a provider that writes
    a fixed internal artifact, exercising the full persistence/retrieval pipeline.
    """

    def provide(
        self, *, run_id: str, task_id: str, state: Mapping[str, object]
    ) -> tuple[ArtifactRef, ...]: ...


class TaskResultFinalizer:
    """Assemble and persist a TaskResult for each terminal workflow outcome.

    Idempotent: if a result for this WorkflowRun already exists, returns its id
    without modifying anything. On conflicting outcome, logs and returns existing.
    """

    def __init__(
        self,
        result_repository: TaskResultWriteRepository,
        *,
        clock: Clock,
        artifact_provider: ResultArtifactProvider | None = None,
    ) -> None:
        self._repo = result_repository
        self._clock = clock
        self._artifact_provider = artifact_provider

    def finalize(
        self,
        *,
        run_id: str,
        task_id: str,
        final_outcome: str,
        state: Mapping[str, object],
    ) -> str:
        """Create (or reuse) the TaskResult for this run; return the result_id."""
        outcome = _OUTCOME_MAP.get(final_outcome)
        if outcome is None:
            raise ValueError(f"Unknown final_outcome for TaskResult: {final_outcome!r}")

        result_id = make_result_id(run_id, final_outcome)

        # Idempotency check: existing result → return same id.
        existing = self._repo.find_by_run(run_id)
        if existing is not None:
            return existing.result_id.value

        now = self._clock.now()
        summary = _extract_summary(state, final_outcome)
        failure = (
            _extract_failure(final_outcome, state)
            if outcome is not TaskResultOutcome.COMPLETED
            else None
        )
        artifacts = (
            self._artifact_provider.provide(run_id=run_id, task_id=task_id, state=state)
            if self._artifact_provider is not None
            else ()
        )

        result = TaskResult(
            result_id=result_id,
            task_id=task_id,
            workflow_run_id=run_id,
            outcome=outcome,
            summary=summary,
            artifact_refs=artifacts,
            failure=failure,
            finalized_at=now,
            result_version=TASK_RESULT_VERSION,
        )

        try:
            self._repo.save(result, artifact_created_at=now.to_iso())
        except ResultConflict:
            # Race: another process finalized first → idempotent, return that id.
            existing_after = self._repo.find_by_run(run_id)
            if existing_after is not None:
                return existing_after.result_id.value
            raise

        return result_id.value


def _extract_summary(state: Mapping[str, object], outcome: str) -> str:
    """Extract a bounded, sanitized business summary from graph state."""
    raw = state.get("business_summary") or state.get("summary")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:MAX_TASK_RESULT_SUMMARY_CHARS]
    phase = state.get("phase")
    if isinstance(phase, str) and phase:
        candidate = f"Workflow {outcome} at phase: {phase}"
        return candidate[:MAX_TASK_RESULT_SUMMARY_CHARS]
    return _SUMMARY_FALLBACK[:MAX_TASK_RESULT_SUMMARY_CHARS]


def _extract_failure(outcome: str, state: Mapping[str, object]) -> FailureInfo:
    """Build a sanitized FailureInfo from outcome and graph state."""
    reason_raw = state.get("error_summary") or state.get("test_failure_category")
    reason: str | None = None
    if isinstance(reason_raw, str) and reason_raw:
        reason = reason_raw[:500]

    code_raw = state.get("test_reason_code")
    code = str(code_raw)[:80] if isinstance(code_raw, str) and code_raw else outcome

    source_raw = state.get("test_recovery_disposition")
    source = "workflow"
    if isinstance(source_raw, str) and source_raw:
        source = source_raw[:80]

    return FailureInfo.for_outcome(code, reason=reason, retryable=False, source=source)
