"""Durable Test Ant execution adapter (PHASE_6_PLAN CP4/CP5, §4/§D.3/§E).

The single graph-facing seam that turns an approved workflow run into a durable, read-only
Test Ant execution.  CP4 owned the attempt lifecycle; CP5 adds structured test evidence
persistence, per-attempt energy delta recording, and population of evidence refs in the
compact outcome (so the graph state carries authoritative evidence pointers).

Context binding (§2.1): the ``context_manifest_digest`` from GraphState binds the test scope
to the approved workflow context. An optional ``expected_context_digest`` set at construction
time fails closed if the incoming digest differs (e.g., a corrupt or replayed state field).
"""

from __future__ import annotations

import hashlib
import json as _json
import time

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.integration import identity as _identity
from ant_orchestrator.integration.test_evidence_persister import TestEvidencePersister
from ant_orchestrator.workers.test.ant import TestAnt
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator, RecoveredAttempt

_LOGICAL_ACTION_SUFFIX = "test"
_COMPACT_OUTCOME_VERSION = 1


def _scope_digest(scope: tuple[str, ...]) -> str:
    """Stable SHA-256 hex of the canonical read scope (NUL-joined, sorted)."""
    content = "\x00".join(sorted(scope))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _to_compact_json(outcome: TestExecutionOutcome) -> str:
    """Serialize the routing-relevant facets of an outcome for durable storage.

    ``evidence_refs`` are excluded — they are re-derived from the identity chain on recovery.
    """
    return _json.dumps(
        {
            "v": _COMPACT_OUTCOME_VERSION,
            "outcome": outcome.outcome.value,
            "disposition": outcome.disposition.value if outcome.disposition else None,
            "reason_code": outcome.reason_code.value if outcome.reason_code else None,
            "category": outcome.category.value if outcome.category else None,
        },
        separators=(",", ":"),
    )


def _from_compact_json(
    json_str: str, attempt_id: str, evidence_refs: tuple[str, ...]
) -> TestExecutionOutcome | None:
    """Deserialize compact outcome; return None on version mismatch or corrupt data."""
    try:
        d = _json.loads(json_str)
        if d.get("v") != _COMPACT_OUTCOME_VERSION:
            return None
        outcome_val = WorkerOutcome(d["outcome"])
        disp_val = d.get("disposition")
        rcode_val = d.get("reason_code")
        cat_val = d.get("category")
        return TestExecutionOutcome(
            outcome=outcome_val,
            attempt_ref=attempt_id,
            disposition=RecoveryDisposition(disp_val) if disp_val else None,
            reason_code=TestReasonCode(rcode_val) if rcode_val else None,
            category=FailureCategory(cat_val) if cat_val else None,
            evidence_refs=evidence_refs,
        )
    except (KeyError, ValueError):
        return None


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
        evidence_persister: TestEvidencePersister | None = None,
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
        self._evidence_persister = evidence_persister

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

        # Window 3 recovery: detect any settled attempt (SUCCEEDED or FAILED) from a run
        # that crashed after after_execute() but before the LangGraph checkpoint committed.
        # Reconstruct the compact outcome from durable authority without calling the backend.
        recovered = self._attempts.find_recoverable_settled_attempt(run_id, logical_action_id)
        if recovered is not None:
            return self._recover_settled_outcome(recovered, run_id, logical_action_id)

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

        started_ms = time.monotonic_ns() // 1_000_000
        result = self._ant.execute(task, scope, run_id)
        wall_time_ms = max(0, (time.monotonic_ns() // 1_000_000) - started_ms)

        if result.cancelled:
            # Cancellation is out-of-band (CP1 deviation §O #4). Do not settle as FAILED.
            self._persist_evidence(
                task_id=task_id,
                run_id=run_id,
                attempt_id=attempt_id,
                logical_action_id=logical_action_id,
                report=result.structured_report,
                wall_time_ms=wall_time_ms,
                context_manifest_digest=context_manifest_digest,
            )
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
            boundary = self._boundary_failure("missing_outcome")
            self._attempts.after_execute(
                attempt_id,
                WorkerOutcome.PERMANENT_FAILURE,
                compact_json=_to_compact_json(boundary),
            )
            return boundary

        evidence_refs = self._persist_evidence(
            task_id=task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            logical_action_id=logical_action_id,
            report=result.structured_report,
            wall_time_ms=wall_time_ms,
            context_manifest_digest=context_manifest_digest,
        )
        # Merge evidence refs before serialising so compact JSON carries no refs
        # (refs are re-derived from identity on recovery, not stored).
        from dataclasses import replace as _replace

        merged_outcome = _replace(
            outcome, evidence_refs=tuple(outcome.evidence_refs) + tuple(evidence_refs)
        )
        self._attempts.after_execute(
            attempt_id,
            outcome.outcome,
            compact_json=_to_compact_json(outcome),  # store without evidence_refs
        )
        return merged_outcome

    def _persist_evidence(
        self,
        *,
        task_id: str,
        run_id: str,
        attempt_id: str,
        logical_action_id: str,
        report: object,
        wall_time_ms: int,
        context_manifest_digest: str,
    ) -> tuple[str, ...]:
        """Persist structured evidence and energy; return opaque refs for state.

        If no persister is injected (CP4 legacy mode) this is a no-op.
        """
        if self._evidence_persister is None:
            return ()
        from ant_orchestrator.workers.test.report import StructuredTestReport

        if not isinstance(report, StructuredTestReport):
            return ()
        attempt_no = self._attempts.get_attempt_no(attempt_id)
        # RETRIES=0 for initial attempt; RETRIES=1 for any retry (delta, not cumulative).
        retry_delta = 0 if attempt_no <= 1 else 1
        persisted = self._evidence_persister.persist(
            task_id=task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            logical_action_id=logical_action_id,
            report=report,
            wall_time_ms=wall_time_ms,
            retry_delta=retry_delta,
            context_manifest_digest=context_manifest_digest,
            read_scope_digest=self._read_scope_digest,
        )
        return (
            f"worker_run:{persisted.worker_run_id}",
            f"evidence:{persisted.evidence_id}",
        )

    def _recover_settled_outcome(
        self,
        recovered: RecoveredAttempt,
        run_id: str,
        logical_action_id: str,
    ) -> TestExecutionOutcome:
        """Reconstruct compact outcome for Window 3 replay without calling the backend."""
        attempt_id = recovered.attempt_id
        wr_id = _identity.test_worker_run_id(run_id, logical_action_id, attempt_id)
        ev_id = _identity.evidence_id(wr_id)
        evidence_refs = (f"worker_run:{wr_id}", f"evidence:{ev_id}")

        # Backward compat: pre-CP6-correction SUCCEEDED row has no compact JSON.
        if recovered.is_succeeded and recovered.compact_json is None:
            return TestExecutionOutcome(
                outcome=WorkerOutcome.SUCCESS,
                attempt_ref=attempt_id,
                evidence_refs=evidence_refs,
            )

        if recovered.compact_json is not None:
            result = _from_compact_json(recovered.compact_json, attempt_id, evidence_refs)
            if result is not None:
                return result

        # Missing or corrupt compact outcome → fail closed (never re-run the backend).
        return self._indeterminate_outcome(attempt_id)

    @staticmethod
    def _indeterminate_outcome(attempt_id: str) -> TestExecutionOutcome:
        """Safe escalation when recovery authority is absent or corrupt (fail-closed)."""
        return TestExecutionOutcome(
            outcome=WorkerOutcome.ESCALATION,
            attempt_ref=attempt_id,
            disposition=RecoveryDisposition.ESCALATE,
            reason_code=TestReasonCode.UNKNOWN_FAILURE,
            category=FailureCategory.UNKNOWN,
        )

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
