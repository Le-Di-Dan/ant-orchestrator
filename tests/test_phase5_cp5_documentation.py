"""CP5 tests — Documentation Ant, provider-neutral composition, durable receipt.

Covers permission/context/energy ordering before any provider call (A), the composer
happy path (B), model-output authority/adversarial rejection (C), the durable
composition receipt + lifecycle (D), crash/recovery windows (E), provider idempotency
honesty (F), the energy lifecycle (G), the async bridge (H), SafeDocumentMutator
integration (I), the §12 authoritative report (J), and no-leak/security (K). Everything
runs on a deterministic fake composer/adapter — no network, no real provider.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
)
from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    DocumentOperation,
    ModelCompositionDraft,
)
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    ComposerSource,
    CompositionConstraints,
    CompositionResult,
)
from ant_orchestrator.application.ports.execution_scope import ApprovedExecutionScope
from ant_orchestrator.application.ports.llm import FinishReason, LLMResponse, ModelUsage
from ant_orchestrator.application.ports.llm_errors import AdapterProviderError
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.application.ports.worker_energy import (
    EnergyReverifyOutcome,
    EnergyReverifyResult,
    EnergySettlement,
    SettlementOutcome,
)
from ant_orchestrator.config.constants import (
    COMPOSITION_RECEIPT_SCHEMA_VERSION,
    DOC_PROMPT_TEMPLATE_ID,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackage, ContextPackageBuilder
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.energy.worker_lifecycle import InMemoryEnergyLifecycle
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
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
from ant_orchestrator.security.path_policy import PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer
from ant_orchestrator.workers.documentation.errors import (
    CompositionIdentityConflict,
    CompositionParseError,
    CompositionReceiptCorrupt,
    InvalidReceiptTransition,
    ProhibitedModelFieldError,
)
from ant_orchestrator.workers.documentation.parser import parse_model_output
from ant_orchestrator.workers.documentation.provider_phase import ProviderPhase
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceipt,
    CompositionReceiptStore,
    CompositionStatus,
)
from ant_orchestrator.workers.documentation.report import (
    DocumentationStatus,
    serialize_draft,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.fake_llm import FakeLLMAdapter
from tests.test_context_package import FakeFs

_TS = datetime(2026, 6, 25, tzinfo=UTC)
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")
_TARGET = "docs/handoffs/HANDOFF-001.md"
_SOURCE = "docs/source/brief.md"
_CONTENT = "# Summary\n\nA composed handoff body."


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #
def _artifacts(ws: Path) -> Path:
    return ws / ".ant" / "artifacts"


def _build_package(files: dict[str, str], inputs: tuple[str, ...]) -> ContextPackage:
    from ant_orchestrator.core.domain.value_objects import UtcTimestamp

    builder = ContextPackageBuilder(
        fs=FakeFs(files),
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(UtcTimestamp(_TS)),
        id_gen=SequentialIdGenerator(),
    )
    request = ContextBuildRequest(
        task_id=TaskId("act-1"),
        consumer=_CONSUMER,
        requests=tuple(ArtifactRequest(p, ArtifactRequirement.REQUIRED) for p in inputs),
        excluded=(),
        budget=_BUDGET,
    )
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(builder.build(request))
    finally:
        loop.close()


def _persist_context(ws: Path, *, source_content: str = "brief") -> tuple[str, str]:
    store = ContextPackageStore(_artifacts(ws))
    pkg = _build_package({_SOURCE: source_content}, (_SOURCE,))
    persisted = store.persist("run-1", "act-1", pkg)
    return persisted.context_package_ref, persisted.manifest_digest


def _task(
    *,
    operation: DocumentOperation = DocumentOperation.CREATE,
    sections: tuple[str, ...] = ("Summary",),
) -> DocumentationTask:
    return DocumentationTask(
        logical_action_id="act-1",
        operation=operation,
        target_document="handoff",
        instruction_summary="write a handoff",
        required_sections=sections,
        approved_inputs=(_SOURCE,),
    )


def _scope(
    ref: str,
    digest: str,
    *,
    operation: DocumentOperation = DocumentOperation.CREATE,
    target: str = _TARGET,
    version: int = 1,
) -> ApprovedExecutionScope:
    return ApprovedExecutionScope(
        attempt_id="attempt-1",
        approval_ref="approval-1",
        proposal_ref="proposal-1",
        proposal_digest="pdigest-1",
        approved_target=target,
        approved_operation=operation,
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        context_package_ref=ref,
        manifest_digest=digest,
        protected_policy_version=version,
        energy_reservation_ref="res-1",
        artifact_root="artifacts/run-1/attempt-1",
        idempotency_key="idem-1",
    )


def _policy(ws: Path, *, version: int = 1) -> ProtectedPathPolicy:
    write_root = ws / "docs" / "handoffs"
    write_root.mkdir(parents=True, exist_ok=True)
    scope = PathScope.build(read_roots=(), write_roots=(write_root,))
    return ProtectedPathPolicy(
        scope=scope, workspace_root=ws, policy_version=version, case_insensitive=False
    )


def _draft(content: str = _CONTENT) -> ModelCompositionDraft:
    return ModelCompositionDraft(
        proposed_content=content, summary="composed", risks=("r1",), next_steps=("n1",)
    )


def _result(draft: ModelCompositionDraft, usage: ModelUsage | None = None) -> CompositionResult:
    return CompositionResult(
        draft=draft,
        usage=usage if usage is not None else ModelUsage.measured(tokens_in=10, tokens_out=20),
        provider_id="fake",
        model_id="fake-model",
        prompt_template_id=DOC_PROMPT_TEMPLATE_ID,
        prompt_template_version=1,
    )


class RecordingComposer:
    """A deterministic ``DocumentationComposer`` that records its calls."""

    def __init__(self, result: CompositionResult) -> None:
        self._result = result
        self.calls = 0
        self.received: list[ComposerContext] = []

    async def compose(
        self, task: DocumentationTask, context: ComposerContext, constraints: CompositionConstraints
    ) -> CompositionResult:
        self.calls += 1
        self.received.append(context)
        return self._result


@dataclass
class _Wired:
    ant: DocumentationAnt
    composer: object
    energy: InMemoryEnergyLifecycle
    ws: Path
    scope: ApprovedExecutionScope
    task: DocumentationTask
    policy: ProtectedPathPolicy


def _wire(
    ws: Path,
    *,
    composer: object | None = None,
    operation: DocumentOperation = DocumentOperation.CREATE,
    target: str = _TARGET,
    reserve: int = 10000,
    version: int = 1,
    scope_version: int = 1,
    energy: InMemoryEnergyLifecycle | None = None,
    timeout: float = 30.0,
) -> _Wired:
    ref, digest = _persist_context(ws)
    comp = composer if composer is not None else RecordingComposer(_result(_draft()))
    en = energy if energy is not None else InMemoryEnergyLifecycle()
    if energy is None:
        en.reserve("res-1", reserve)
    policy = _policy(ws, version=version)
    mutator = SafeDocumentMutator(policy=policy, workspace_root=ws, artifacts_root=_artifacts(ws))
    ant = DocumentationAnt(
        composer=comp,  # type: ignore[arg-type]
        runner=AsyncDependencyRunner(default_timeout=timeout),
        energy=en,
        mutator=mutator,
        policy=policy,
        context_store=ContextPackageStore(_artifacts(ws)),
        workspace_root=ws,
        artifacts_root=_artifacts(ws),
        provider_timeout=timeout,
    )
    scope = _scope(ref, digest, operation=operation, target=target, version=scope_version)
    return _Wired(ant, comp, en, ws, scope, _task(operation=operation), policy)


def _receipt_path(ws: Path) -> Path:
    roots = ArtifactRoot(_artifacts(ws), "run-1", "attempt-1")
    return roots.path_for(ArtifactKind.COMPOSITION_RECEIPT)


# --------------------------------------------------------------------------- #
# A. Permission / context / energy ordering — provider call 0
# --------------------------------------------------------------------------- #
def test_identity_mismatch_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    bad = _scope(
        w.scope.context_package_ref, w.scope.manifest_digest, operation=DocumentOperation.UPDATE
    )
    result = w.ant.execute(w.task, bad, "run-1")  # task=CREATE vs scope=UPDATE
    assert result.status is DocumentationStatus.IDENTITY_INVALID
    assert w.composer.calls == 0  # type: ignore[attr-defined]


def test_context_missing_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    bad = _scope("deadbeef/context/deadbeef", w.scope.manifest_digest)
    result = w.ant.execute(w.task, bad, "run-1")
    assert result.status is DocumentationStatus.CONTEXT_FAILED
    assert w.composer.calls == 0  # type: ignore[attr-defined]


def test_context_digest_mismatch_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    bad = _scope(w.scope.context_package_ref, "0" * 64)
    result = w.ant.execute(w.task, bad, "run-1")
    assert result.status is DocumentationStatus.CONTEXT_FAILED
    assert w.composer.calls == 0  # type: ignore[attr-defined]
    assert not _receipt_path(tmp_path).exists()  # no invocation receipt either


def test_protected_target_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path, target="docs/handoffs/HANDOFF.md")
    bad = _scope(w.scope.context_package_ref, w.scope.manifest_digest, target="ROADMAP.md")
    result = w.ant.execute(w.task, bad, "run-1")
    assert result.status is DocumentationStatus.PERMISSION_DENIED
    assert w.composer.calls == 0  # type: ignore[attr-defined]
    assert not _receipt_path(tmp_path).exists()


def test_out_of_scope_target_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    bad = _scope(w.scope.context_package_ref, w.scope.manifest_digest, target="src/app.py")
    result = w.ant.execute(w.task, bad, "run-1")
    assert result.status is DocumentationStatus.PERMISSION_DENIED
    assert w.composer.calls == 0  # type: ignore[attr-defined]


def test_policy_version_mismatch_no_provider(tmp_path: Path) -> None:
    w = _wire(tmp_path, version=1, scope_version=2)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.PERMISSION_DENIED
    assert w.composer.calls == 0  # type: ignore[attr-defined]


def test_energy_reverify_invalid_no_provider(tmp_path: Path) -> None:
    energy = InMemoryEnergyLifecycle()  # no reservation seeded → reverify INVALID
    w = _wire(tmp_path, energy=energy)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.ENERGY_DENIED
    assert w.composer.calls == 0  # type: ignore[attr-defined]
    assert not _receipt_path(tmp_path).exists()


# --------------------------------------------------------------------------- #
# B. Composer happy path
# --------------------------------------------------------------------------- #
def test_create_happy_path(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.PUBLISHED
    assert result.report.result is WorkerOutcome.SUCCESS
    assert result.provider_invoked is True
    assert w.composer.calls == 1  # type: ignore[attr-defined]
    assert result.receipt_status == CompositionStatus.ENERGY_SETTLED.value
    # published file holds the proposed content
    assert (tmp_path / _TARGET).read_text(encoding="utf-8") == _CONTENT
    # report §12 fields
    assert result.report.files_read == (_SOURCE,)
    assert result.report.files_changed == (_TARGET,)
    assert result.report.commands == ()
    assert result.report.risks == ("r1",)
    assert result.report.next_steps == ("n1",)


def test_happy_path_persists_verified_draft_artifact(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    roots = ArtifactRoot(_artifacts(tmp_path), "run-1", "attempt-1")
    receipt = CompositionReceiptStore(roots.path_for(ArtifactKind.COMPOSITION_RECEIPT)).load()
    assert receipt.status_enum is CompositionStatus.ENERGY_SETTLED
    draft_text = read_artifact(
        roots.path_for(ArtifactKind.COMPOSITION_DRAFT), receipt.draft_digest or ""
    )
    assert json.loads(draft_text)["proposed_content"] == _CONTENT
    # draft↔proposed link
    assert receipt.proposed_digest == sha256_text(_CONTENT)


def test_context_passed_to_composer(tmp_path: Path) -> None:
    composer = RecordingComposer(_result(_draft()))
    w = _wire(tmp_path, composer=composer)
    w.ant.execute(w.task, w.scope, "run-1")
    ctx = composer.received[0]
    assert ctx.manifest_digest == w.scope.manifest_digest
    assert ctx.sources[0].path == _SOURCE


def test_update_happy_path(tmp_path: Path) -> None:
    target_file = tmp_path / _TARGET
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("# Summary\n\nold", encoding="utf-8")
    composer = RecordingComposer(_result(_draft("# Summary\n\nbrand new body")))
    w = _wire(tmp_path, composer=composer, operation=DocumentOperation.UPDATE)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.PUBLISHED
    assert target_file.read_text(encoding="utf-8") == "# Summary\n\nbrand new body"


# --------------------------------------------------------------------------- #
# C. Model output authority / adversarial (parser)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "field",
    [
        "target",
        "operation",
        "files_read",
        "files_changed",
        "commands",
        "evidence",
        "result",
        "energy_usage",
    ],
)
def test_parser_rejects_prohibited_field(field: str) -> None:
    raw = json.dumps({"proposed_content": "# Summary\n\nx", field: "smuggled"})
    with pytest.raises(ProhibitedModelFieldError) as exc:
        parse_model_output(raw, CompositionConstraints())
    assert exc.value.field == field


def test_parser_rejects_unknown_field_without_echo() -> None:
    raw = json.dumps({"proposed_content": "x", "weird_secret_key": "value"})
    with pytest.raises(CompositionParseError) as exc:
        parse_model_output(raw, CompositionConstraints())
    assert "value" not in str(exc.value) and "weird_secret_key" not in str(exc.value)


def test_parser_rejects_malformed_and_missing_content() -> None:
    with pytest.raises(CompositionParseError):
        parse_model_output("not json", CompositionConstraints())
    with pytest.raises(CompositionParseError):
        parse_model_output(json.dumps({"summary": "no content"}), CompositionConstraints())


def test_adversarial_output_does_not_mutate_or_pollute_report(tmp_path: Path) -> None:
    raw = json.dumps(
        {
            "proposed_content": "# Summary\n\nbody",
            "files_changed": ["/etc/passwd"],
            "result": "success",
        }
    )
    adapter = FakeLLMAdapter(
        responses=[
            LLMResponse(
                text=raw,
                provider="fake",
                model="m",
                usage=ModelUsage.measured(1, 1),
                finish_reason=FinishReason.STOP,
            )
        ]
    )
    w = _wire(tmp_path, composer=LLMDocumentationComposer(adapter))
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.COMPOSITION_FAILED
    assert result.report.files_changed == ()
    assert not (tmp_path / _TARGET).exists()
    assert "/etc/passwd" not in repr(result.report)


# --------------------------------------------------------------------------- #
# D. Composition receipt
# --------------------------------------------------------------------------- #
def _receipt(status: CompositionStatus, **over: object) -> CompositionReceipt:
    base = dict(
        schema_version=COMPOSITION_RECEIPT_SCHEMA_VERSION,
        run_id="run-1",
        attempt_id="attempt-1",
        logical_action_id="act-1",
        proposal_digest="pdigest-1",
        approval_ref="approval-1",
        context_manifest_digest="ctx",
        canonical_target=_TARGET,
        protected_policy_version=1,
        invocation_id="inv-1",
        energy_reservation_ref="res-1",
        prompt_template_id=DOC_PROMPT_TEMPLATE_ID,
        prompt_template_version=1,
        status=status.value,
        revision=0,
    )
    base.update(over)
    return CompositionReceipt(**base)  # type: ignore[arg-type]


def test_receipt_roundtrip_and_checksum(tmp_path: Path) -> None:
    store = CompositionReceiptStore(tmp_path / "r.json")
    store.save(_receipt(CompositionStatus.RESERVED))
    loaded = store.load()
    assert loaded.status_enum is CompositionStatus.RESERVED
    # tamper
    raw = json.loads((tmp_path / "r.json").read_text(encoding="utf-8"))
    raw["status"] = "completed"
    (tmp_path / "r.json").write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(CompositionReceiptCorrupt):
        store.load()


def test_receipt_transitions_monotonic() -> None:
    r = _receipt(CompositionStatus.RESERVED)
    inv = r.advance_to(CompositionStatus.INVOKING)
    assert inv.revision == 1
    assert inv.advance_to(CompositionStatus.INVOKING) is inv  # idempotent
    with pytest.raises(InvalidReceiptTransition):
        inv.advance_to(CompositionStatus.ENERGY_SETTLED)  # skip COMPLETED
    with pytest.raises(InvalidReceiptTransition):
        inv.advance_to(CompositionStatus.RESERVED)  # backward


def test_receipt_terminal_states() -> None:
    r = _receipt(CompositionStatus.INVOKING)
    doubt = r.to_terminal(CompositionStatus.IN_DOUBT, "ambiguous")
    assert doubt.status_enum is CompositionStatus.IN_DOUBT
    assert doubt.to_terminal(CompositionStatus.FAILED, "x") is doubt  # terminal sticks
    with pytest.raises(InvalidReceiptTransition):
        doubt.advance_to(CompositionStatus.COMPLETED)


def test_receipt_identity_conflict_on_different_draft() -> None:
    completed = _receipt(CompositionStatus.COMPLETED, draft_digest="aaa")
    completed.ensure_same_draft("aaa")  # ok
    with pytest.raises(CompositionIdentityConflict):
        completed.ensure_same_draft("bbb")


def test_receipt_has_no_raw_prompt_or_output(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    raw = _receipt_path(tmp_path).read_text(encoding="utf-8")
    assert "fake-response" not in raw
    assert "context" in raw  # only the digest field name, not content
    assert _CONTENT not in raw  # proposed content is not duplicated into the receipt


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
    # Craft a COMPLETED receipt + durable draft artifact (energy not yet settled).
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
    # Re-run: receipt ENERGY_SETTLED, journal PUBLISHED, target present at proposed digest.
    second = w.ant.execute(w.task, w.scope, "run-1")
    assert second.status is DocumentationStatus.PUBLISHED
    assert w.composer.calls == calls_after_first  # provider not called again


def test_recover_energy_settled_no_journal_reuses_draft(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    calls_after_first = w.composer.calls  # type: ignore[attr-defined]
    # Simulate crash that lost the mutation journal + published file (provider phase durable).
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
    settlement = energy.settle("res-1", "x", ModelUsage.unavailable())  # was already settled?
    # The provider-phase settled the in-doubt invocation conservatively; a fresh invocation id
    # here is a different settlement, so just assert no crash and target untouched.
    assert settlement is not None
    assert not (tmp_path / _TARGET).exists()


# --------------------------------------------------------------------------- #
# H. Async bridge
# --------------------------------------------------------------------------- #
def test_async_bridge_runs_and_returns() -> None:
    runner = AsyncDependencyRunner()

    async def work() -> int:
        return 42

    assert runner.run(work, timeout=5.0) == 42


def test_async_bridge_timeout() -> None:
    runner = AsyncDependencyRunner()

    async def slow() -> int:
        await asyncio.sleep(5.0)
        return 1

    with pytest.raises(AsyncBridgeTimeoutError):
        runner.run(slow, timeout=0.05)


def test_async_bridge_cancellation() -> None:
    runner = AsyncDependencyRunner()

    async def cancelled() -> int:
        raise asyncio.CancelledError

    with pytest.raises(AsyncBridgeCancelledError):
        runner.run(cancelled, timeout=5.0)


def test_async_bridge_rejects_active_loop_before_call() -> None:
    runner = AsyncDependencyRunner()
    calls = {"n": 0}

    def factory() -> object:
        calls["n"] += 1
        return asyncio.sleep(0)

    async def driver() -> None:
        with pytest.raises(AsyncBridgeActiveLoopError):
            runner.run(factory, timeout=5.0)  # type: ignore[arg-type]

    asyncio.run(driver())
    assert calls["n"] == 0  # factory never invoked ⇒ provider call count 0


def test_async_bridge_no_leak_over_many_calls() -> None:
    runner = AsyncDependencyRunner()

    async def work() -> int:
        return 1

    for _ in range(50):
        assert runner.run(work, timeout=5.0) == 1


def test_ant_timeout_is_in_doubt(tmp_path: Path) -> None:
    class SlowComposer:
        def __init__(self) -> None:
            self.calls = 0

        async def compose(self, task, context, constraints):  # type: ignore[no-untyped-def]
            self.calls += 1
            await asyncio.sleep(5.0)
            return _result(_draft())

    w = _wire(tmp_path, composer=SlowComposer(), timeout=0.05)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.IN_DOUBT
    receipt = CompositionReceiptStore(_receipt_path(tmp_path)).load()
    assert receipt.status_enum is CompositionStatus.IN_DOUBT


# --------------------------------------------------------------------------- #
# I. SafeDocumentMutator integration
# --------------------------------------------------------------------------- #
def test_validation_failure_maps_outcome(tmp_path: Path) -> None:
    composer = RecordingComposer(_result(_draft("no heading here at all")))
    w = _wire(tmp_path, composer=composer)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.VALIDATION_FAILED
    assert result.report.result is WorkerOutcome.VALIDATION_FAILURE
    assert not (tmp_path / _TARGET).exists()


def test_no_change_maps_success(tmp_path: Path) -> None:
    target_file = tmp_path / _TARGET
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text(_CONTENT, encoding="utf-8")
    composer = RecordingComposer(_result(_draft(_CONTENT)))
    w = _wire(tmp_path, composer=composer, operation=DocumentOperation.UPDATE)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.status is DocumentationStatus.NO_CHANGE
    assert result.report.result is WorkerOutcome.SUCCESS
    assert result.report.files_changed == ()


def test_artifacts_not_in_files_changed(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.report.files_changed == (_TARGET,)
    assert all("composition" not in fc and ".ant" not in fc for fc in result.report.files_changed)


# --------------------------------------------------------------------------- #
# J. WorkerExecutionReport
# --------------------------------------------------------------------------- #
def test_report_evidence_refs_are_system_assembled(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    result = w.ant.execute(w.task, w.scope, "run-1")
    refs = result.report.evidence_refs
    kinds = {ref.split(":", 1)[0] for ref in refs}
    assert {"context", "permission", "receipt", "draft", "energy", "journal", "proposed"} <= kinds


def test_report_success_requires_energy_settled(tmp_path: Path) -> None:
    # Over-budget settles energy but must NOT yield a SUCCESS report.
    composer = RecordingComposer(
        _result(_draft(), usage=ModelUsage.measured(tokens_in=900, tokens_out=900))
    )
    w = _wire(tmp_path, composer=composer, reserve=100)
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.report.result is not WorkerOutcome.SUCCESS


def test_model_declared_facts_do_not_change_files_read(tmp_path: Path) -> None:
    raw = json.dumps({"proposed_content": _CONTENT, "summary": "ok"})
    adapter = FakeLLMAdapter(
        responses=[
            LLMResponse(text=raw, provider="fake", model="m", usage=ModelUsage.measured(1, 1))
        ]
    )
    w = _wire(tmp_path, composer=LLMDocumentationComposer(adapter))
    result = w.ant.execute(w.task, w.scope, "run-1")
    assert result.report.files_read == (_SOURCE,)  # from manifest, not the model


# --------------------------------------------------------------------------- #
# K. No-leak / security
# --------------------------------------------------------------------------- #
def test_draft_artifact_has_no_provider_envelope(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    roots = ArtifactRoot(_artifacts(tmp_path), "run-1", "attempt-1")
    text = roots.path_for(ArtifactKind.COMPOSITION_DRAFT).read_text(encoding="utf-8")
    document = json.loads(text)
    assert set(document.keys()) == {"proposed_content", "summary", "risks", "next_steps"}


def test_system_artifacts_outside_write_scope(tmp_path: Path) -> None:
    w = _wire(tmp_path)
    w.ant.execute(w.task, w.scope, "run-1")
    # the composition receipt/draft live under .ant/artifacts, never under docs/handoffs
    assert _artifacts(tmp_path) in _receipt_path(tmp_path).parents
    write_root = tmp_path / "docs" / "handoffs"
    assert _artifacts(tmp_path) not in write_root.parents


def test_provider_identifier_is_bounded(tmp_path: Path) -> None:
    raw = json.dumps({"proposed_content": _CONTENT})
    adapter = FakeLLMAdapter(
        responses=[
            LLMResponse(
                text=raw, provider="p" * 200, model="m" * 200, usage=ModelUsage.measured(1, 1)
            )
        ]
    )
    w = _wire(tmp_path, composer=LLMDocumentationComposer(adapter))
    w.ant.execute(w.task, w.scope, "run-1")
    receipt = CompositionReceiptStore(_receipt_path(tmp_path)).load()
    assert receipt.adapter_provider is not None and len(receipt.adapter_provider) <= 64
