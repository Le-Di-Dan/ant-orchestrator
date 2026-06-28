"""Durable Test Ant execution adapter (PHASE_6_PLAN CP4, §4/§D.3/§E).

Mirrors ``execution_adapter.py`` for the Test Ant: the single graph-facing seam that turns
an approved workflow run into a durable, read-only Test Ant execution. The adapter owns the
attempt lifecycle (create/reuse/settle), context binding, scope assembly, and compact outcome
construction. It never retries, escalates, persists reports, writes energy, or creates a
terminal handoff — those are CP5 responsibilities.

Context binding (§2.1): the ``context_manifest_digest`` from GraphState binds the test scope
to the approved workflow context. An optional ``expected_context_digest`` set at construction
time fails closed if the incoming digest differs (e.g., a corrupt or replayed state field).
"""

from __future__ import annotations

import hashlib

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.workers.test.ant import TestAnt
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator

_LOGICAL_ACTION_SUFFIX = "test"


def _scope_digest(scope: tuple[str, ...]) -> str:
    """Stable SHA-256 hex of the canonical read scope (NUL-joined, sorted)."""
    content = "\x00".join(sorted(scope))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class DurableTestExecution:
    """Implements :class:`TestExecutionPort` over the Test Ant + AttemptOrchestrator.

    Responsibilities in scope for CP4:
    * Create/reuse/settle ``ExecutionAttempt`` via AttemptOrchestrator.
    * Build ``TestTask`` + ``TestExecutionScope`` with context binding (§2.1).
    * Verify ``context_manifest_digest`` before backend execution (fail closed on mismatch).
    * Call ``TestAnt.execute`` exactly once per new attempt.
    * Return compact ``TestExecutionOutcome`` (JSON-safe, no raw output/path).
    * Handle stale lease → INDETERMINATE per existing lifecycle semantics.

    Out of scope for CP4 (deferred to CP5):
    * Persist ``StructuredTestReport`` or evidence.
    * Record ``EnergyMeasurement``.
    * Emit terminal handoff.
    """

    __test__ = False  # domain term; not a pytest test class

    def __init__(
        self,
        *,
        ant: TestAnt,
        attempt_orchestrator: AttemptOrchestrator,
        canonical_read_scope: tuple[str, ...],
        command_profile_key: str,
        isolation_ref: str | None = None,
        expected_context_digest: str = "",
    ) -> None:
        if not canonical_read_scope:
            raise InvariantViolation("DurableTestExecution.canonical_read_scope must be non-empty")
        self._ant = ant
        self._attempts = attempt_orchestrator
        self._read_scope = canonical_read_scope
        self._command_profile_key = command_profile_key
        self._isolation_ref = isolation_ref
        self._expected_context_digest = expected_context_digest
        self._read_scope_digest = _scope_digest(canonical_read_scope)

    def execute(
        self,
        *,
        task_id: str,
        run_id: str,
        context_manifest_digest: str = "",
    ) -> TestExecutionOutcome:
        """Execute (or idempotently recover) one read-only test attempt.

        Context binding (fail closed): if ``expected_context_digest`` is set at construction
        and differs from ``context_manifest_digest`` provided by the workflow state, the
        backend is NOT called and a boundary failure outcome is returned.
        """
        if not task_id or not run_id:
            raise InvariantViolation("DurableTestExecution.execute requires task_id and run_id")

        if self._expected_context_digest and (
            context_manifest_digest != self._expected_context_digest
        ):
            return self._boundary_failure("context_digest_mismatch")

        logical_action_id = f"{task_id}-{_LOGICAL_ACTION_SUFFIX}"
        attempt_id = self._attempts.before_execute(run_id, logical_action_id)

        scope = TestExecutionScope(
            attempt_id=attempt_id,
            run_id=run_id,
            logical_action_id=logical_action_id,
            canonical_read_scope=self._read_scope,
            command_profile_key=self._command_profile_key,
            idempotency_key=f"{run_id}\x00{logical_action_id}\x00{attempt_id}",
            isolation_ref=self._isolation_ref,
            context_manifest_digest=context_manifest_digest,
            read_scope_digest=self._read_scope_digest,
        )
        task = TestTask(
            task_ref=task_id,
            logical_action_id=logical_action_id,
            command_key=self._command_profile_key,
        )

        result = self._ant.execute(task, scope, run_id)

        if result.cancelled:
            # Cancellation is out-of-band (CP1 deviation §O #4). Do not settle as FAILED.
            return TestExecutionOutcome(
                outcome=WorkerOutcome.PERMANENT_FAILURE,
                attempt_ref=attempt_id,
                disposition=RecoveryDisposition.TERMINAL_CANCELLED,
                reason_code=TestReasonCode.EXECUTION_CANCELLED,
                category=FailureCategory.UNKNOWN,
            )

        outcome = result.outcome
        if outcome is None:
            # Defensive: assemble() should always produce an outcome for non-cancelled runs.
            self._attempts.after_execute(attempt_id, WorkerOutcome.PERMANENT_FAILURE)
            return self._boundary_failure("missing_outcome")

        self._attempts.after_execute(attempt_id, outcome.outcome)
        return outcome

    @staticmethod
    def _boundary_failure(detail: str) -> TestExecutionOutcome:
        """Compact TERMINAL_FAILED outcome for adapter-level boundary violations."""
        return TestExecutionOutcome(
            outcome=WorkerOutcome.PERMANENT_FAILURE,
            attempt_ref=f"boundary-{detail}",
            disposition=RecoveryDisposition.TERMINAL_FAILED,
            reason_code=TestReasonCode.EXECUTION_BOUNDARY_DENIED,
            category=FailureCategory.EXECUTION_BOUNDARY_FAILURE,
        )


__all__ = ["DurableTestExecution"]
