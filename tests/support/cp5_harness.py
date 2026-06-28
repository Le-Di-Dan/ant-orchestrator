"""Shared harness for CP5 documentation test suites."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

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
    CompositionConstraints,
    CompositionResult,
)
from ant_orchestrator.application.ports.execution_scope import ApprovedExecutionScope
from ant_orchestrator.application.ports.llm import ModelUsage
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
from ant_orchestrator.execution.mutation_artifacts import ArtifactKind, ArtifactRoot
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.security.path_policy import PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceipt,
    CompositionStatus,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.test_context_package import FakeFs

_TS = datetime(2026, 6, 25, tzinfo=UTC)
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")
_TARGET = "docs/handoffs/HANDOFF-001.md"
_SOURCE = "docs/source/brief.md"
_CONTENT = "# Summary\n\nA composed handoff body."


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
        self,
        task: DocumentationTask,
        context: ComposerContext,
        constraints: CompositionConstraints,
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
