"""Assemble the Test Ant's three outputs from one classified run (PHASE_6_PLAN CP3).

From a single :class:`ClassifiedExecution` plus the gathered run context this builds:

* the durable-facing :class:`StructuredTestReport` (§D.6),
* the reused :class:`WorkerExecutionReport` (``files_changed=()``, ``provider_invoked=False``,
  logical command form only), and
* the graph-facing :class:`TestExecutionOutcome` (CP1).

Cancellation is handled per the CP1 deviation: it is NOT forced through
``worker_outcome_for`` (which intentionally raises for ``TERMINAL_CANCELLED``). A cancelled
run yields a report only; the worker/graph outcome is left out-of-band for CP4/CP6.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.application.ports.document_worker import WorkerExecutionReport
from ant_orchestrator.application.ports.test_execution import (
    TestExecutionOutcome,
    worker_outcome_for,
)
from ant_orchestrator.application.ports.test_isolation import IsolatedExecutionResult
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.config.constants import TEST_WORKER_KIND
from ant_orchestrator.core.domain.test_failure import RecoveryDisposition
from ant_orchestrator.workers.test.classifier import ClassifiedExecution
from ant_orchestrator.workers.test.provisioning import (
    BoundedRunOutput,
    CleanupOutcome,
    CleanupStatus,
    ProvisionedSnapshot,
)
from ant_orchestrator.workers.test.report import (
    StructuredTestReport,
    TestCounts,
    TestProcessStatus,
)


@dataclass(frozen=True, slots=True)
class RunContext:
    """The gathered, sanitized inputs assembly needs (no host path, no raw output)."""

    __test__ = False  # domain term; not a pytest test class

    run_id: str
    attempt_ref: str
    logical_action_ref: str
    command_key: str
    profile_version: int
    sanitized_argv: tuple[str, ...]
    argv_digest: str
    approved_targets: tuple[str, ...]
    files_read: tuple[str, ...]
    counts: TestCounts = field(default_factory=TestCounts.unavailable)
    provisioned: ProvisionedSnapshot | None = None
    run_result: IsolatedExecutionResult | None = None
    output: BoundedRunOutput | None = None
    cleanup: CleanupOutcome = field(default_factory=lambda: CleanupOutcome(CleanupStatus.CLEAN))
    backend_ref: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


@dataclass(frozen=True, slots=True)
class TestExecutionResult:
    """The Test Ant's complete, JSON-safe result for one run (read-only worker)."""

    __test__ = False  # domain term; not a pytest test class

    structured_report: StructuredTestReport
    worker_report: WorkerExecutionReport | None
    outcome: TestExecutionOutcome | None
    cancelled: bool = False
    provider_invoked: bool = False


def assemble(classified: ClassifiedExecution, ctx: RunContext) -> TestExecutionResult:
    """Build the structured report + worker report + graph outcome from one verdict."""
    report = _build_report(classified, ctx)
    classification = classified.classification
    if classification is not None and (
        classification.recommended_disposition is RecoveryDisposition.TERMINAL_CANCELLED
    ):
        return TestExecutionResult(report, worker_report=None, outcome=None, cancelled=True)

    evidence = classification.evidence.evidence_refs if classification else ()
    worker_outcome, outcome = _build_outcome(classified, ctx, evidence)
    worker_report = _build_worker_report(classified, ctx, worker_outcome, evidence)
    return TestExecutionResult(report, worker_report=worker_report, outcome=outcome)


def _build_report(classified: ClassifiedExecution, ctx: RunContext) -> StructuredTestReport:
    snapshot = ctx.provisioned
    verified = snapshot.is_verified if snapshot is not None else False
    completed = classified.process_status in (
        TestProcessStatus.COMPLETED,
        TestProcessStatus.INTERRUPTED,
    )
    run = ctx.run_result
    exit_code = run.exit_code if (run is not None and completed) else None
    classification = classified.classification
    out = ctx.output
    return StructuredTestReport(
        run_ref=ctx.run_id,
        attempt_ref=ctx.attempt_ref,
        logical_action_ref=ctx.logical_action_ref,
        worker_kind=TEST_WORKER_KIND,
        command_key=ctx.command_key,
        command_profile_version=ctx.profile_version,
        sanitized_argv=ctx.sanitized_argv,
        argv_digest=ctx.argv_digest,
        approved_targets=ctx.approved_targets,
        process_status=classified.process_status,
        test_result=classified.test_result,
        counts=ctx.counts,
        snapshot_verified=verified,
        snapshot_manifest_digest=(
            snapshot.manifest_digest if snapshot is not None and verified else None
        ),
        cleanup_status=ctx.cleanup.status,
        diagnostic_hint=classified.diagnostic_hint,
        duration_ms=run.duration_ms if run is not None else 0,
        started_at=ctx.started_at,
        finished_at=ctx.finished_at,
        exit_code=exit_code,
        isolation_backend_ref=ctx.backend_ref,
        isolation_status=run.status.value if run is not None else None,
        output_truncated=out.truncated if out is not None else False,
        output_original_bytes=out.original_bytes if out is not None else 0,
        output_redaction_applied=out.redaction_applied if out is not None else False,
        failure_category=classification.category if classification else None,
        reason_code=classification.reason_code if classification else None,
        transience=classification.transience if classification else None,
        recovery_disposition=classification.recommended_disposition if classification else None,
        evidence_refs=classification.evidence.evidence_refs if classification else (),
    )


def _build_outcome(
    classified: ClassifiedExecution, ctx: RunContext, evidence: tuple[str, ...]
) -> tuple[WorkerOutcome, TestExecutionOutcome]:
    classification = classified.classification
    if classification is None:
        outcome = TestExecutionOutcome(WorkerOutcome.SUCCESS, attempt_ref=ctx.attempt_ref)
        return WorkerOutcome.SUCCESS, outcome
    worker_outcome = worker_outcome_for(classification.recommended_disposition)
    outcome = TestExecutionOutcome(
        outcome=worker_outcome,
        attempt_ref=ctx.attempt_ref,
        disposition=classification.recommended_disposition,
        reason_code=classification.reason_code,
        category=classification.category,
        evidence_refs=evidence,
    )
    return worker_outcome, outcome


def _build_worker_report(
    classified: ClassifiedExecution,
    ctx: RunContext,
    worker_outcome: WorkerOutcome,
    evidence: tuple[str, ...],
) -> WorkerExecutionReport:
    summary = f"Test {ctx.command_key}: {classified.test_result.value}"
    return WorkerExecutionReport(
        summary=summary,
        files_read=ctx.files_read,
        files_changed=(),
        commands=(f"{ctx.command_key}@v{ctx.profile_version}",),
        result=worker_outcome,
        evidence_refs=evidence,
    )
