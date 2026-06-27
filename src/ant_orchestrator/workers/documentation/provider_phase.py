"""Provider phase: durable composition receipt + composer call + energy settlement (CP5).

Owns everything between "energy reverified" and "draft ready for the mutator". It
persists a RESERVED→INVOKING receipt, invokes the composer through the async bridge
EXACTLY once, persists + digest-verifies the typed draft, records COMPLETED, settles
energy, then records ENERGY_SETTLED. On recovery it never re-calls the provider once a
draft is durably COMPLETED, and an ambiguous INVOKING (no provider reconciliation
available) fails closed as IN_DOUBT. No raw prompt/response/exception is ever persisted.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    ModelCompositionDraft,
)
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    CompositionConstraints,
    DocumentationComposer,
)
from ant_orchestrator.application.ports.execution_scope import ApprovedExecutionScope
from ant_orchestrator.application.ports.llm import ModelUsage, UsageStatus
from ant_orchestrator.application.ports.llm_errors import AdapterError
from ant_orchestrator.application.ports.worker_energy import (
    SettlementOutcome,
    WorkerEnergyLifecycle,
)
from ant_orchestrator.config.constants import (
    COMPOSITION_RECEIPT_SCHEMA_VERSION,
    DOC_PROMPT_TEMPLATE_ID,
    DOC_PROMPT_TEMPLATE_VERSION,
)
from ant_orchestrator.core.domain.value_objects import TokenCount
from ant_orchestrator.execution.mutation_artifacts import (
    ArtifactKind,
    ArtifactRoot,
    read_artifact,
    sha256_text,
    write_artifact,
)
from ant_orchestrator.infrastructure.async_bridge import (
    AsyncBridgeActiveLoopError,
    AsyncBridgeCancelledError,
    AsyncBridgeTimeoutError,
    AsyncDependencyRunner,
)
from ant_orchestrator.workers.documentation.errors import (
    CompositionParseError,
    ProhibitedModelFieldError,
)
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceipt,
    CompositionReceiptStore,
    CompositionStatus,
)
from ant_orchestrator.workers.documentation.report import (
    DocumentationStatus,
    deserialize_draft,
    serialize_draft,
)


@dataclass(frozen=True, slots=True)
class ProviderPhaseOutcome:
    """The provider phase's result. ``control`` is None iff the mutator may proceed."""

    draft: ModelCompositionDraft | None
    receipt: CompositionReceipt | None
    provider_invoked: bool
    control: DocumentationStatus | None
    failure_code: str | None


class ProviderPhase:
    """Drives the durable composition receipt around a single composer invocation."""

    def __init__(
        self,
        *,
        composer: DocumentationComposer,
        runner: AsyncDependencyRunner,
        energy: WorkerEnergyLifecycle,
        timeout: float,
    ) -> None:
        self._composer = composer
        self._runner = runner
        self._energy = energy
        self._timeout = timeout

    def run(
        self,
        *,
        task: DocumentationTask,
        scope: ApprovedExecutionScope,
        run_id: str,
        relpath: str,
        context: ComposerContext,
        constraints: CompositionConstraints,
        invocation_id: str,
        roots: ArtifactRoot,
    ) -> ProviderPhaseOutcome:
        store = CompositionReceiptStore(roots.path_for(ArtifactKind.COMPOSITION_RECEIPT))
        ctx = _Call(task, scope, run_id, relpath, context, constraints, invocation_id, roots, store)
        if store.exists():
            return self._recover(store.load(), ctx)
        reserved = self._new_receipt(ctx, CompositionStatus.RESERVED)
        store.save(reserved)  # durable RESERVED before any invocation
        return self._invoke(reserved, ctx)

    # --- recovery ----------------------------------------------------------
    def _recover(self, receipt: CompositionReceipt, ctx: _Call) -> ProviderPhaseOutcome:
        status = receipt.status_enum
        if status is CompositionStatus.RESERVED:
            return self._invoke(receipt, ctx)  # provider not yet called: safe to proceed
        if status is CompositionStatus.INVOKING:
            doubt = receipt.to_terminal(CompositionStatus.IN_DOUBT, "provider_invocation_ambiguous")
            ctx.store.save(doubt)
            return ProviderPhaseOutcome(
                None, doubt, False, DocumentationStatus.IN_DOUBT, "provider_invocation_ambiguous"
            )
        if status is CompositionStatus.FAILED:
            return ProviderPhaseOutcome(
                None, receipt, False, DocumentationStatus.COMPOSITION_FAILED, receipt.failure_code
            )
        if status is CompositionStatus.IN_DOUBT:
            return ProviderPhaseOutcome(
                None, receipt, False, DocumentationStatus.IN_DOUBT, receipt.failure_code
            )
        draft = self._load_draft(receipt, ctx)
        if status is CompositionStatus.COMPLETED:
            return self._settle(receipt, draft, ctx, provider_invoked=False)
        return ProviderPhaseOutcome(draft, receipt, False, None, None)  # ENERGY_SETTLED

    # --- fresh invocation --------------------------------------------------
    def _invoke(self, receipt: CompositionReceipt, ctx: _Call) -> ProviderPhaseOutcome:
        invoking = (
            receipt
            if receipt.status_enum is CompositionStatus.INVOKING
            else receipt.advance_to(CompositionStatus.INVOKING)
        )
        ctx.store.save(invoking)  # durable INVOKING BEFORE the external call
        try:
            result = self._runner.run(
                lambda: self._composer.compose(ctx.task, ctx.context, ctx.constraints),
                timeout=self._timeout,
            )
        except (AsyncBridgeTimeoutError, AsyncBridgeCancelledError):
            ctx.store.save(invoking.to_terminal(CompositionStatus.IN_DOUBT, "provider_timeout"))
            return ProviderPhaseOutcome(
                None, None, True, DocumentationStatus.IN_DOUBT, "provider_timeout"
            )
        except AsyncBridgeActiveLoopError:
            # The bridge guard fires BEFORE the coroutine is created: provider call count 0.
            ctx.store.save(invoking.to_terminal(CompositionStatus.FAILED, "async_active_loop"))
            return ProviderPhaseOutcome(
                None, None, False, DocumentationStatus.COMPOSITION_FAILED, "async_active_loop"
            )
        except ProhibitedModelFieldError:
            ctx.store.save(invoking.to_terminal(CompositionStatus.FAILED, "prohibited_model_field"))
            return ProviderPhaseOutcome(
                None, None, True, DocumentationStatus.COMPOSITION_FAILED, "prohibited_model_field"
            )
        except CompositionParseError:
            ctx.store.save(
                invoking.to_terminal(CompositionStatus.FAILED, "composition_parse_error")
            )
            return ProviderPhaseOutcome(
                None, None, True, DocumentationStatus.COMPOSITION_FAILED, "composition_parse_error"
            )
        except AdapterError:
            # The call happened and may have consumed energy: settle conservatively, fail closed.
            self._energy.settle(
                ctx.scope.energy_reservation_ref, ctx.invocation_id, ModelUsage.unavailable()
            )
            ctx.store.save(invoking.to_terminal(CompositionStatus.FAILED, "provider_error"))
            return ProviderPhaseOutcome(
                None, None, True, DocumentationStatus.COMPOSITION_FAILED, "provider_error"
            )

        draft = result.draft
        draft_digest = write_artifact(
            ctx.roots.path_for(ArtifactKind.COMPOSITION_DRAFT), serialize_draft(draft)
        )
        read_artifact(ctx.roots.path_for(ArtifactKind.COMPOSITION_DRAFT), draft_digest)
        completed = invoking.complete(
            provider=result.provider_id,
            model=result.model_id,
            draft_ref=ctx.roots.ref_for(ArtifactKind.COMPOSITION_DRAFT),
            draft_digest=draft_digest,
            proposed_digest=sha256_text(draft.proposed_content),
            usage_status=result.usage.status.value,
            usage_tokens_total=_usage_total(result.usage),
        )
        ctx.store.save(completed)
        return self._settle(completed, draft, ctx, provider_invoked=True)

    # --- settlement --------------------------------------------------------
    def _settle(
        self,
        receipt: CompositionReceipt,
        draft: ModelCompositionDraft,
        ctx: _Call,
        *,
        provider_invoked: bool,
    ) -> ProviderPhaseOutcome:
        settlement = self._energy.settle(
            ctx.scope.energy_reservation_ref, ctx.invocation_id, _receipt_usage(receipt)
        )
        if settlement.outcome is SettlementOutcome.FAILED:
            return ProviderPhaseOutcome(
                draft,
                receipt,
                provider_invoked,
                DocumentationStatus.SETTLEMENT_FAILED,
                "energy_settlement_failed",
            )
        settled = receipt.settled(
            settlement_ref=settlement.settlement_ref,
            actual_tokens=settlement.actual_tokens,
            fallback_used=settlement.fallback_used,
            over_budget=settlement.outcome is SettlementOutcome.OVER_BUDGET,
        )
        ctx.store.save(settled)
        if settlement.outcome is SettlementOutcome.OVER_BUDGET:
            return ProviderPhaseOutcome(
                draft,
                settled,
                provider_invoked,
                DocumentationStatus.OVER_BUDGET,
                "energy_over_budget",
            )
        return ProviderPhaseOutcome(draft, settled, provider_invoked, None, None)

    # --- helpers -----------------------------------------------------------
    def _load_draft(self, receipt: CompositionReceipt, ctx: _Call) -> ModelCompositionDraft:
        digest = receipt.draft_digest or ""
        text = read_artifact(ctx.roots.path_for(ArtifactKind.COMPOSITION_DRAFT), digest)
        draft = deserialize_draft(text)
        receipt.ensure_same_draft(sha256_text(serialize_draft(draft)))
        return draft

    def _new_receipt(self, ctx: _Call, status: CompositionStatus) -> CompositionReceipt:
        return CompositionReceipt(
            schema_version=COMPOSITION_RECEIPT_SCHEMA_VERSION,
            run_id=ctx.run_id,
            attempt_id=ctx.scope.attempt_id,
            logical_action_id=ctx.task.logical_action_id,
            proposal_digest=ctx.scope.proposal_digest,
            approval_ref=ctx.scope.approval_ref,
            context_manifest_digest=ctx.scope.manifest_digest,
            canonical_target=ctx.relpath,
            protected_policy_version=ctx.scope.protected_policy_version,
            invocation_id=ctx.invocation_id,
            energy_reservation_ref=ctx.scope.energy_reservation_ref,
            prompt_template_id=DOC_PROMPT_TEMPLATE_ID,
            prompt_template_version=DOC_PROMPT_TEMPLATE_VERSION,
            status=status.value,
            revision=0,
        )


@dataclass(frozen=True, slots=True)
class _Call:
    task: DocumentationTask
    scope: ApprovedExecutionScope
    run_id: str
    relpath: str
    context: ComposerContext
    constraints: CompositionConstraints
    invocation_id: str
    roots: ArtifactRoot
    store: CompositionReceiptStore


def _usage_total(usage: ModelUsage) -> int | None:
    if usage.tokens_total is not None:
        return usage.tokens_total.value
    if usage.tokens_in is not None and usage.tokens_out is not None:
        return usage.tokens_in.value + usage.tokens_out.value
    return None


def _receipt_usage(receipt: CompositionReceipt) -> ModelUsage:
    """Reconstruct a settlement-equivalent usage from the durable receipt facts.

    The energy ledger only consumes the total; an UNAVAILABLE marker triggers the
    conservative fallback. This keeps settlement identical on the fresh and recovery paths.
    """
    if receipt.usage_status == UsageStatus.UNAVAILABLE.value or receipt.usage_tokens_total is None:
        return ModelUsage.unavailable()
    total = receipt.usage_tokens_total
    return ModelUsage(UsageStatus.MEASURED, TokenCount(total), TokenCount(0), TokenCount(total))
