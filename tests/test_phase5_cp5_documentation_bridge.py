"""CP5 — Documentation Ant: async bridge, mutator integration, report, security (H-K)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.application.ports.llm import LLMResponse, ModelUsage
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.execution.mutation_artifacts import ArtifactKind, ArtifactRoot
from ant_orchestrator.infrastructure.async_bridge import (
    AsyncBridgeActiveLoopError,
    AsyncBridgeCancelledError,
    AsyncBridgeTimeoutError,
    AsyncDependencyRunner,
)
from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer
from ant_orchestrator.workers.documentation.receipt import (
    CompositionReceiptStore,
    CompositionStatus,
)
from ant_orchestrator.workers.documentation.report import DocumentationStatus
from tests.support.cp5_harness import (
    _CONTENT,
    _SOURCE,
    _TARGET,
    RecordingComposer,
    _artifacts,
    _draft,
    _receipt_path,
    _result,
    _wire,
)
from tests.support.fake_llm import FakeLLMAdapter

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
    assert len(receipt.adapter_provider or "") <= 128
    assert len(receipt.model_id or "") <= 128
