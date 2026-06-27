"""Durable documentation execution adapter (PHASE_5_PLAN CP6 §4/§11/§14).

The single graph-facing seam that turns an approved, bound proposal into a durable
side effect. It loads + digest-verifies the proposal, creates/reuses the stable attempt,
seeds the durable energy reservation, assembles the immutable scope, runs the Documentation
Ant (provider-neutral; the Ant itself recovers a durable draft without re-calling the
provider), and — only on a published/no-change result — persists WorkerRun/Evidence/energy
in one unit of work, completes the mutation journal, and settles the attempt. Re-invoking is
idempotent end to end: no second provider call, no second charge, no duplicate record. No
raw prompt/output/exception is ever surfaced — only a compact, sanitized outcome.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionOutcome,
)
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.energy.durable_lifecycle import DurableEnergyLifecycle
from ant_orchestrator.execution.mutation_artifacts import ArtifactKind, ArtifactRoot
from ant_orchestrator.execution.prepared_mutation import JournalStore, MutationJournal
from ant_orchestrator.integration.errors import IntegrationError, ProposalAuthorityError
from ant_orchestrator.integration.evidence_envelope import EvidenceEnvelope
from ant_orchestrator.integration.persistence_mapper import ExecutionPersister, PersistencePlan
from ant_orchestrator.integration.proposal_store import PreparedExecution, ProposalStore
from ant_orchestrator.integration.scope_assembly import assemble_scope, reservation_ref_for
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceipt,
    CompositionReceiptStore,
)
from ant_orchestrator.workers.documentation.report import DocumentationResult, DocumentationStatus
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator

_PUBLISHED = frozenset({DocumentationStatus.PUBLISHED, DocumentationStatus.NO_CHANGE})


class DocumentationExecutionAdapter:
    """Implements ``DocumentationExecutionPort`` over the Documentation Ant + persistence."""

    def __init__(
        self,
        *,
        ant: DocumentationAnt,
        attempt_orchestrator: AttemptOrchestrator,
        energy: DurableEnergyLifecycle,
        persister: ExecutionPersister,
        proposal_store: ProposalStore,
        artifacts_root: Path,
    ) -> None:
        self._ant = ant
        self._attempts = attempt_orchestrator
        self._energy = energy
        self._persister = persister
        self._proposals = proposal_store
        self._artifacts_root = artifacts_root

    def execute(
        self,
        *,
        task_id: str,
        run_id: str,
        proposal_ref: str,
        proposal_digest: str,
        approval_ref: str,
    ) -> DocumentationExecutionOutcome:
        try:
            prepared = self._proposals.load(proposal_ref, proposal_digest)
        except ProposalAuthorityError:
            return DocumentationExecutionOutcome(
                outcome=WorkerOutcome.PERMANENT_FAILURE,
                attempt_ref="",
                failure_code="proposal_authority_invalid",
            )

        logical_action_id = prepared.proposal.logical_action_id
        attempt_id = self._attempts.before_execute(run_id, logical_action_id)
        self._energy.reserve(
            reservation_ref_for(prepared.proposal, attempt_id),
            prepared.proposal.energy_estimate.value,
        )
        roots = ArtifactRoot(self._artifacts_root, run_id, attempt_id)
        scope = assemble_scope(
            proposal=prepared.proposal,
            approval_ref=approval_ref,
            proposal_ref=proposal_ref,
            attempt_id=attempt_id,
            artifact_root_ref=roots.ref_for(ArtifactKind.JOURNAL).rsplit("/", 1)[0],
        )

        result = self._ant.execute(prepared.task, scope, run_id)
        if result.status not in _PUBLISHED:
            return self._controlled_failure(attempt_id, result)
        return self._finalize(task_id, run_id, attempt_id, prepared, roots, result)

    # --- success path ------------------------------------------------------
    def _finalize(
        self,
        task_id: str,
        run_id: str,
        attempt_id: str,
        prepared: PreparedExecution,
        roots: ArtifactRoot,
        result: DocumentationResult,
    ) -> DocumentationExecutionOutcome:
        receipt = CompositionReceiptStore(roots.path_for(ArtifactKind.COMPOSITION_RECEIPT)).load()
        journal_store = JournalStore(roots.path_for(ArtifactKind.JOURNAL))
        journal = journal_store.load()
        envelope = self._build_envelope(
            run_id, attempt_id, prepared, roots, receipt, journal, result
        )
        plan = PersistencePlan(
            task_id=task_id,
            run_id=run_id,
            attempt_id=attempt_id,
            logical_action_id=prepared.proposal.logical_action_id,
            proposal_digest=prepared.proposal_digest,
            succeeded=True,
            files_read=result.report.files_read,
            files_changed=result.report.files_changed,
            commands=result.report.commands,
            envelope=envelope,
            settlement_tokens=receipt.settlement_actual_tokens or 0,
        )
        persisted = self._persister.persist(plan, journal_store)
        self._attempts.after_execute(attempt_id, WorkerOutcome.SUCCESS)
        refs = (
            *result.report.evidence_refs,
            f"worker_run:{persisted.worker_run_id}",
            f"evidence:{persisted.evidence_id}",
        )
        return DocumentationExecutionOutcome(
            outcome=WorkerOutcome.SUCCESS,
            attempt_ref=attempt_id,
            evidence_refs=refs,
            provider_invoked=result.provider_invoked,
        )

    @staticmethod
    def _build_envelope(
        run_id: str,
        attempt_id: str,
        prepared: PreparedExecution,
        roots: ArtifactRoot,
        receipt: CompositionReceipt,
        journal: MutationJournal,
        result: DocumentationResult,
    ) -> EvidenceEnvelope:
        proposal = prepared.proposal
        j = journal
        return EvidenceEnvelope(
            run_id=run_id,
            logical_action_id=proposal.logical_action_id,
            attempt_id=attempt_id,
            proposal_ref=prepared.proposal_ref,
            proposal_digest=prepared.proposal_digest,
            approval_ref=receipt.approval_ref,
            context_package_ref=proposal.context_package_ref,
            manifest_digest=proposal.manifest_digest,
            protected_policy_version=proposal.protected_policy_version,
            permission_decision="allow",
            receipt_ref=roots.ref_for(ArtifactKind.COMPOSITION_RECEIPT),
            receipt_status=receipt.status,
            draft_digest=receipt.draft_digest or "",
            energy_estimate_tokens=proposal.energy_estimate.value,
            energy_reservation_ref=reservation_ref_for(proposal, attempt_id),
            energy_actual_tokens=receipt.settlement_actual_tokens or 0,
            energy_fallback_used=receipt.settlement_fallback_used,
            energy_over_budget=receipt.over_budget,
            energy_settlement_ref=receipt.energy_settlement_ref or "",
            journal_ref=roots.ref_for(ArtifactKind.JOURNAL),
            journal_status=j.status,
            target_digest=j.proposed_digest,
            validation_result="pass" if j.validation_ok else "fail",
            before_ref=j.before_ref,
            proposed_ref=j.proposed_ref,
            diff_ref=j.diff_ref,
            adapter_provider=receipt.adapter_provider or "",
            model_id=receipt.model_id or "",
        )

    # --- controlled-failure path ------------------------------------------
    def _controlled_failure(
        self, attempt_id: str, result: DocumentationResult
    ) -> DocumentationExecutionOutcome:
        outcome = result.report.result
        self._attempts.after_execute(attempt_id, outcome)
        return DocumentationExecutionOutcome(
            outcome=outcome,
            attempt_ref=attempt_id,
            evidence_refs=result.report.evidence_refs,
            failure_code=result.failure_code or result.status.value,
            provider_invoked=result.provider_invoked,
        )


__all__ = ["DocumentationExecutionAdapter", "IntegrationError"]
