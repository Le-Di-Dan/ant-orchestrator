"""CP5 — Documentation Ant: crash/recovery windows, energy lifecycle (E-G)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    ComposerSource,
    CompositionConstraints,
)
from ant_orchestrator.application.ports.execution_scope import ApprovedExecutionScope
from ant_orchestrator.application.ports.llm import ModelUsage
from ant_orchestrator.application.ports.llm_errors import AdapterProviderError
from ant_orchestrator.application.ports.worker_energy import (
    EnergyReverifyOutcome,
    EnergyReverifyResult,
    EnergySettlement,
    SettlementOutcome,
)
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.energy.worker_lifecycle import InMemoryEnergyLifecycle
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
from ant_orchestrator.execution.mutation_artifacts import (
    ArtifactKind,
    ArtifactRoot,
    sha256_text,
    write_artifact,
)
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer
from ant_orchestrator.workers.documentation.provider_phase import ProviderPhase
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceiptStore,
    CompositionStatus,
)
from ant_orchestrator.workers.documentation.report import DocumentationStatus, serialize_draft
from tests.support.cp5_harness import (
    _CONTENT,
    _SOURCE,
    _TARGET,
    RecordingComposer,
    _artifacts,
    _draft,
    _persist_context,
    _policy,
    _receipt,
    _receipt_path,
    _result,
    _scope,
    _task,
    _wire,
)
from tests.support.fake_llm import FakeLLMAdapter

# --------------------------------------------------------------------------- #
# E. Crash / recovery windows (ProviderPhase + Ant)
# --------------------------------------------------------------------------- #


def _provider_phase(
    ws: Path, composer: object, energy: InMemoryEnergyLifecycle, *, timeout: float = 30.0
) -> ProviderPhase:
    return ProviderPhase(
        composer=composer,  # type: ignore[arg-type]
        runner=AsyncDependencyRunner(default_timeout=timeout),
        energy=energy,
        timeout=timeout,
    )


def _run_phase(ws: Path, phase: ProviderPhase, scope: ApprovedExecutionScope) -> object:
    roots = ArtifactRoot(_artifacts(ws), "run-1", "attempt-1")
    context = ComposerContext(
        manifest_digest=scope.manifest_digest, sources=(ComposerSource(_SOURCE, "brief"),)
    )
    return phase.run(
        task=_task(),
        scope=scope,
        run_id="run-1",
        relpath=_TARGET,
        context=context,
        constraints=CompositionConstraints(),
        invocation_id="inv-1",
        roots=roots,
    )


def test_recover_invoking_receipt_is_in_doubt(tmp_path: Path) -> None:
    ref, digest = _persist_context(tmp_path)
    scope = _scope(ref, digest)
    energy = InMemoryEnergyLifecycle()
    energy.reserve("res-1", 10000)
    CompositionReceiptStore(_receipt_path(tmp_path)).save(_receipt(CompositionStatus.INVOKING))
    composer = RecordingComposer(_result(_draft()))
    outcome = _run_phase(tmp_path, _provider_phase(tmp_path, composer, energy), scope)
    assert outcome.control is DocumentationStatus.IN_DOUBT  # type: ignore[attr-defined]
    assert composer.calls == 0  # provider not re-called on ambiguity


def test_recover_reserved_receipt_resumes_fresh(tmp_path: Path) -> None:
    ref, digest = _persist_context(tmp_path)
    scope = _scope(ref, digest)
    energy = InMemoryEnergyLifecycle()
    energy.reserve("res-1", 10000)
    CompositionReceiptStore(_receipt_path(tmp_path)).save(_receipt(CompositionStatus.RESERVED))
    composer = RecordingComposer(_result(_draft()))
    outcome = _run_phase(tmp_path, _provider_phase(tmp_path, composer, energy), scope)
    assert outcome.control is None  # type: ignore[attr-defined]
    assert composer.calls == 1  # RESERVED ⇒ provider not yet called, safe to invoke


def test_recover_completed_receipt_reuses_draft(tmp_path: Path) -> None:
    ref, digest = _persist_context(tmp_path)
    scope = _scope(ref, digest)
    energy = InMemoryEnergyLifecycle()
    energy.reserve("res-1", 10000)
    roots = ArtifactRoot(_artifacts(tmp_path), "run-1", "attempt-1")
    draft_digest = write_artifact(
        roots.path_for(ArtifactKind.COMPOSITION_DRAFT), serialize_draft(_draft())
    )
    completed = _receipt(
        CompositionStatus.COMPLETED,
        draft_ref=roots.ref_for(ArtifactKind.COMPOSITION_DRAFT),
        draft_digest=draft_digest,
        proposed_digest=sha256_text(_CONTENT),
        usage_status="measured",
        usage_tokens_total=30,
    )
    CompositionReceiptStore(_receipt_path(tmp_path)).save(completed)
    composer = RecordingComposer(_result(_draft()))
    outcome = _run_phase(tmp_path, _provider_phase(tmp_path, composer, energy), scope)
    assert composer.calls == 0  # durable COMPLETED ⇒ no provider call
    assert outcome.control is None  # type: ignore[attr-defined]
    assert outcome.receipt.status_enum is CompositionStatus.ENERGY_SETTLED  # type: ignore[attr-defined]


def test_recover_after_publish_uses_mutation_recovery(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    first = w.ant.execute(w.task, w.scope, "run-1")
    assert first.status is DocumentationStatus.PUBLISHED
    calls_after_first = w.composer.calls  # type: ignore[attr-defined]
    second = w.ant.execute(w.task, w.scope, "run-1")
    assert second.status is DocumentationStatus.PUBLISHED
    assert w.composer.calls == calls_after_first  # provider not called again


def test_recover_energy_settled_no_journal_reuses_draft(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    calls_after_first = w.composer.calls  # type: ignore[attr-defined]
    roots = ArtifactRoot(_artifacts(tmp_path), "run-1", "attempt-1")
    roots.path_for(ArtifactKind.JOURNAL).unlink()
    (tmp_path / _TARGET).unlink()
    second = w.ant.execute(w.task, w.scope, "run-1")
    assert second.status is DocumentationStatus.PUBLISHED
    assert w.composer.calls == calls_after_first  # draft reused, provider not called


# --------------------------------------------------------------------------- #
# G. Energy lifecycle
# --------------------------------------------------------------------------- #


def test_usage_unavailable_uses_conservative_fallback(tmp_path: Path) -> None:
    composer = RecordingComposer(_result(_draft(), usage=ModelUsage.unavailable()))
    w = _wire(tmp_path, composer=composer, reserve=500)
    w.ant.execute(w.task, w.scope, "run-1")
    receipt = CompositionReceiptStore(_receipt_path(tmp_path)).load()
    assert receipt.settlement_fallback_used is True
    assert receipt.settlement_actual_tokens == 500  # reserved amount, never zero


def test_over_budget_settles_without_mutation(tmp_path: Path) -> None:
    composer = RecordingComposer(
        _result(_draft(), usage=ModelUsage.measured(tokens_in=400, tokens_out=400))
    )
    w = _wire(tmp_path, composer=composer, reserve=100)  # actual 800 > reserved 100
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.OVER_BUDGET
    assert not (tmp_path / _TARGET).exists()  # no mutation on over-budget
    receipt = CompositionReceiptStore(_receipt_path(tmp_path)).load()
    assert receipt.over_budget is True
    assert receipt.status_enum is CompositionStatus.ENERGY_SETTLED  # still settled (honest)


class _FailingEnergy:
    def reverify(self, reservation_ref: str) -> EnergyReverifyResult:
        return EnergyReverifyResult(EnergyReverifyOutcome.VALID, "ok")

    def settle(
        self, reservation_ref: str, invocation_id: str, usage: ModelUsage
    ) -> EnergySettlement:
        return EnergySettlement(SettlementOutcome.FAILED, 0, False, "failed", invocation_id)


def test_settlement_failure_blocks_mutation(tmp_path: Path) -> None:
    ref, digest = _persist_context(tmp_path)
    composer = RecordingComposer(_result(_draft()))
    policy = _policy(tmp_path)
    mutator = SafeDocumentMutator(
        policy=policy, workspace_root=tmp_path, artifacts_root=_artifacts(tmp_path)
    )
    ant = DocumentationAnt(
        composer=composer,  # type: ignore[arg-type]
        runner=AsyncDependencyRunner(),
        energy=_FailingEnergy(),  # type: ignore[arg-type]
        mutator=mutator,
        policy=policy,
        context_store=ContextPackageStore(_artifacts(tmp_path)),
        workspace_root=tmp_path,
        artifacts_root=_artifacts(tmp_path),
    )
    result = ant.execute(_task(), _scope(ref, digest), "run-1")
    assert result.status is DocumentationStatus.SETTLEMENT_FAILED
    assert not (tmp_path / _TARGET).exists()


def test_provider_error_settles_conservatively(tmp_path: Path) -> None:
    adapter = FakeLLMAdapter(error=AdapterProviderError("boom", provider="fake"))
    energy = InMemoryEnergyLifecycle()
    energy.reserve("res-1", 700)
    w = _wire(tmp_path, composer=LLMDocumentationComposer(adapter), energy=energy)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.COMPOSITION_FAILED
    settlement = energy.settle("res-1", "x", ModelUsage.unavailable())
    assert settlement is not None
    assert not (tmp_path / _TARGET).exists()
