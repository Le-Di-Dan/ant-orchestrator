"""Documentation Ant — end-to-end fresh/recovery execution (PHASE_5_PLAN CP5 / §10).

Fresh ordering (carry-forward §1): validate identity → verify+load context → permission
preflight (CP3) → reverify energy → provider phase (durable receipt) → settle energy →
build the CP4 ``MutationRequest`` → ``SafeDocumentMutator`` → assemble the authoritative
``WorkerExecutionReport``. The model is never authoritative for any operational fact, the
provider is never invoked before permission/energy pass, and a durably COMPLETED draft is
reused on recovery without a second provider call. CP5 stops at journal ``PUBLISHED`` — no
DB persistence, no graph wiring, no journal ``COMPLETED``.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    ModelCompositionDraft,
)
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    ComposerSource,
    CompositionConstraints,
    DocumentationComposer,
)
from ant_orchestrator.application.ports.execution_scope import ApprovedExecutionScope
from ant_orchestrator.application.ports.worker_energy import WorkerEnergyLifecycle
from ant_orchestrator.config.constants import DEFAULT_TIMEOUT_SECONDS
from ant_orchestrator.context.store import ContextPackageStore, ContextStoreError
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
from ant_orchestrator.execution.mutation_artifacts import ArtifactKind, ArtifactRoot, sha256_text
from ant_orchestrator.execution.mutation_recovery import (
    DbObservation,
    MutationRecovery,
    RecoveryAction,
    TargetKind,
    TargetObservation,
)
from ant_orchestrator.execution.mutation_types import (
    MutationOutcome,
    MutationRequest,
    MutationResult,
)
from ant_orchestrator.execution.prepared_mutation import JournalError, JournalStore
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.security.path_policy import PathAccess
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.workers.documentation.provider_phase import (
    ProviderPhase,
    ProviderPhaseOutcome,
)
from ant_orchestrator.workers.documentation.report import (
    DocumentationResult,
    DocumentationStatus,
    build_report,
)

_REUSE_ACTIONS = frozenset(
    {
        RecoveryAction.MARK_PUBLISHED,
        RecoveryAction.FINALIZE_COMPLETED,
        RecoveryAction.NOOP,
        RecoveryAction.PERSIST_EXECUTION_RECORDS,
    }
)
_REEXECUTE_ACTIONS = frozenset({RecoveryAction.FRESH_EXECUTE, RecoveryAction.PUBLISH_THEN_VERIFY})


class DocumentationAnt:
    """Provider-backed (via ``LLMAdapter``) Documentation Ant — testable with fakes."""

    def __init__(
        self,
        *,
        composer: DocumentationComposer,
        runner: AsyncDependencyRunner,
        energy: WorkerEnergyLifecycle,
        mutator: SafeDocumentMutator,
        policy: ProtectedPathPolicy,
        context_store: ContextPackageStore,
        workspace_root: Path,
        artifacts_root: Path,
        provider_timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._provider = ProviderPhase(
            composer=composer, runner=runner, energy=energy, timeout=provider_timeout
        )
        self._energy = energy
        self._mutator = mutator
        self._policy = policy
        self._context_store = context_store
        self._ws = workspace_root.resolve()
        self._artifacts_root = artifacts_root

    def execute(
        self, task: DocumentationTask, scope: ApprovedExecutionScope, run_id: str
    ) -> DocumentationResult:
        if not run_id or task.operation is not scope.approved_operation:
            return self._fail(DocumentationStatus.IDENTITY_INVALID, "identity_invalid", ())

        try:
            sources = self._context_store.load(scope.context_package_ref, scope.manifest_digest)
        except ContextStoreError:
            return self._fail(DocumentationStatus.CONTEXT_FAILED, "context_verification_failed", ())
        files_read = tuple(source.path for source in sources)

        decision = self._policy.check(scope.approved_target, PathAccess.WRITE)
        if decision.decision is not PolicyDecision.ALLOW or decision.canonical_relpath is None:
            return self._fail(
                DocumentationStatus.PERMISSION_DENIED, "permission_denied", files_read
            )
        if decision.protected_policy_version != scope.protected_policy_version:
            return self._fail(
                DocumentationStatus.PERMISSION_DENIED, "permission_version_mismatch", files_read
            )
        relpath = decision.canonical_relpath

        reverify = self._energy.reverify(scope.energy_reservation_ref)
        if not reverify.ok:
            return self._fail(
                DocumentationStatus.ENERGY_DENIED, "energy_reverify_failed", files_read
            )

        roots = ArtifactRoot(self._artifacts_root, run_id, scope.attempt_id)
        context = ComposerContext(
            manifest_digest=scope.manifest_digest,
            sources=tuple(ComposerSource(s.path, s.content) for s in sources),
        )
        outcome = self._provider.run(
            task=task,
            scope=scope,
            run_id=run_id,
            relpath=relpath,
            context=context,
            constraints=CompositionConstraints(),
            invocation_id=self._invocation_id(run_id, scope, task),
            roots=roots,
        )
        if outcome.control is not None or outcome.draft is None:
            status = outcome.control or DocumentationStatus.COMPOSITION_FAILED
            return self._fail(
                status,
                outcome.failure_code or status.value,
                files_read,
                provider_invoked=outcome.provider_invoked,
                receipt_status=_receipt_status(outcome),
            )

        return self._mutate(task, scope, run_id, relpath, outcome, roots, files_read)

    # --- mutation phase ----------------------------------------------------
    def _mutate(
        self,
        task: DocumentationTask,
        scope: ApprovedExecutionScope,
        run_id: str,
        relpath: str,
        outcome: ProviderPhaseOutcome,
        roots: ArtifactRoot,
        files_read: tuple[str, ...],
    ) -> DocumentationResult:
        draft = outcome.draft
        assert draft is not None
        proposed_digest = sha256_text(draft.proposed_content)
        request = self._build_request(task, scope, run_id, draft)
        journal_store = JournalStore(roots.path_for(ArtifactKind.JOURNAL))

        if journal_store.exists():
            recovered = self._recover_mutation(journal_store, relpath, proposed_digest)
            if recovered is not None:
                status, result = recovered
                return self._result_from_mutation(
                    status, result, relpath, outcome, roots, files_read
                )

        result = self._mutator.execute(request)
        status = _map_mutation(result.outcome)
        return self._result_from_mutation(status, result, relpath, outcome, roots, files_read)

    def _recover_mutation(
        self, journal_store: JournalStore, relpath: str, proposed_digest: str
    ) -> tuple[DocumentationStatus, MutationResult | None] | None:
        try:
            journal = journal_store.load()
        except JournalError:
            return (DocumentationStatus.MUTATION_FAILED, None)
        if journal.proposed_digest != proposed_digest:
            return (DocumentationStatus.MUTATION_FAILED, None)  # draft↔journal digest mismatch
        observation = self._observe_target(relpath)
        decision = MutationRecovery().decide(journal, observation, DbObservation())
        if decision.action in _REUSE_ACTIONS:
            return (DocumentationStatus.PUBLISHED, None)  # already published; no re-mutate
        if decision.action in _REEXECUTE_ACTIONS:
            return None  # fall through to a normal mutator call
        return (DocumentationStatus.MUTATION_FAILED, None)  # FAIL_CONFLICT / FAIL_TARGET_MISMATCH

    def _observe_target(self, relpath: str) -> TargetObservation:
        target = self._ws / Path(relpath)
        if target.is_symlink() or not target.exists() or not target.is_file():
            return TargetObservation(TargetKind.ABSENT)
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        return TargetObservation(TargetKind.PRESENT, digest)

    @staticmethod
    def _build_request(
        task: DocumentationTask,
        scope: ApprovedExecutionScope,
        run_id: str,
        draft: ModelCompositionDraft,
    ) -> MutationRequest:
        return MutationRequest(
            run_id=run_id,
            attempt_id=scope.attempt_id,
            logical_action_id=task.logical_action_id,
            proposal_digest=scope.proposal_digest,
            context_digest=scope.manifest_digest,
            approval_ref=scope.approval_ref,
            requested_target=scope.approved_target,
            operation=task.operation,
            proposed_content=draft.proposed_content,
            required_sections=task.required_sections,
            protected_policy_version=scope.protected_policy_version,
        )

    # --- result assembly ---------------------------------------------------
    def _result_from_mutation(
        self,
        status: DocumentationStatus,
        result: MutationResult | None,
        relpath: str,
        outcome: ProviderPhaseOutcome,
        roots: ArtifactRoot,
        files_read: tuple[str, ...],
    ) -> DocumentationResult:
        published = status in (DocumentationStatus.PUBLISHED, DocumentationStatus.NO_CHANGE)
        files_changed = (relpath,) if status is DocumentationStatus.PUBLISHED else ()
        evidence = self._evidence(relpath, outcome, roots, result)
        report = build_report(
            status=status,
            summary_fallback=f"Documentation {relpath}",
            files_read=files_read,
            files_changed=files_changed,
            evidence_refs=evidence,
            draft=outcome.draft if published else None,
        )
        return DocumentationResult(
            status=status,
            report=report,
            provider_invoked=outcome.provider_invoked,
            failure_code=None if published else status.value,
            receipt_status=_receipt_status(outcome),
        )

    def _evidence(
        self,
        relpath: str,
        outcome: ProviderPhaseOutcome,
        roots: ArtifactRoot,
        result: MutationResult | None,
    ) -> tuple[str, ...]:
        receipt = outcome.receipt
        refs = [
            f"context:{receipt.context_manifest_digest}" if receipt else "context:",
            f"permission:allow:{relpath}",
            f"receipt:{roots.ref_for(ArtifactKind.COMPOSITION_RECEIPT)}",
            f"draft:{roots.ref_for(ArtifactKind.COMPOSITION_DRAFT)}",
        ]
        if receipt and receipt.energy_settlement_ref:
            refs.append(f"energy:{receipt.energy_settlement_ref}")
        if result is not None and result.journal_ref:
            refs.append(f"journal:{result.journal_ref}")
        if result is not None and result.proposed_ref:
            refs.append(f"proposed:{result.proposed_ref}")
        return tuple(refs)

    def _fail(
        self,
        status: DocumentationStatus,
        failure_code: str,
        files_read: tuple[str, ...],
        *,
        provider_invoked: bool = False,
        receipt_status: str | None = None,
    ) -> DocumentationResult:
        report = build_report(
            status=status,
            summary_fallback=f"documentation worker failed: {status.value}",
            files_read=files_read,
            files_changed=(),
            evidence_refs=(),
            draft=None,
        )
        return DocumentationResult(
            status=status,
            report=report,
            provider_invoked=provider_invoked,
            failure_code=failure_code,
            receipt_status=receipt_status,
        )

    @staticmethod
    def _invocation_id(run_id: str, scope: ApprovedExecutionScope, task: DocumentationTask) -> str:
        seed = (
            f"{run_id}\x00{scope.attempt_id}\x00{task.logical_action_id}\x00{scope.proposal_digest}"
        )
        return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _map_mutation(outcome: MutationOutcome) -> DocumentationStatus:
    if outcome is MutationOutcome.PUBLISHED:
        return DocumentationStatus.PUBLISHED
    if outcome is MutationOutcome.NO_CHANGE:
        return DocumentationStatus.NO_CHANGE
    if outcome is MutationOutcome.VALIDATION_FAILED:
        return DocumentationStatus.VALIDATION_FAILED
    if outcome is MutationOutcome.CONFLICT:
        return DocumentationStatus.MUTATION_CONFLICT
    return DocumentationStatus.MUTATION_FAILED


def _receipt_status(outcome: ProviderPhaseOutcome) -> str | None:
    return outcome.receipt.status if outcome.receipt is not None else None


__all__ = ["DocumentationAnt"]
