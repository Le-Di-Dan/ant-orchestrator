"""CP5 — Documentation Ant: permission ordering, composer happy path, parser authority, receipt."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.application.ports.llm import FinishReason, LLMResponse, ModelUsage
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.energy.worker_lifecycle import InMemoryEnergyLifecycle
from ant_orchestrator.execution.mutation_artifacts import (
    ArtifactKind,
    ArtifactRoot,
    read_artifact,
    sha256_text,
)
from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer
from ant_orchestrator.workers.documentation.errors import (
    CompositionIdentityConflict,
    CompositionParseError,
    CompositionReceiptCorrupt,
    InvalidReceiptTransition,
    ProhibitedModelFieldError,
)
from ant_orchestrator.workers.documentation.parser import parse_model_output
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
    _receipt,
    _receipt_path,
    _result,
    _scope,
    _wire,
)
from tests.support.fake_llm import FakeLLMAdapter

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
    assert (tmp_path / _TARGET).read_text(encoding="utf-8") == _CONTENT
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
    from ant_orchestrator.application.ports.documentation_composer import CompositionConstraints

    raw = json.dumps({"proposed_content": "# Summary\n\nx", field: "smuggled"})
    with pytest.raises(ProhibitedModelFieldError) as exc:
        parse_model_output(raw, CompositionConstraints())
    assert exc.value.field == field


def test_parser_rejects_unknown_field_without_echo() -> None:
    from ant_orchestrator.application.ports.documentation_composer import CompositionConstraints

    raw = json.dumps({"proposed_content": "x", "weird_secret_key": "value"})
    with pytest.raises(CompositionParseError) as exc:
        parse_model_output(raw, CompositionConstraints())
    assert "value" not in str(exc.value) and "weird_secret_key" not in str(exc.value)


def test_parser_rejects_malformed_and_missing_content() -> None:
    from ant_orchestrator.application.ports.documentation_composer import CompositionConstraints

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


def test_receipt_roundtrip_and_checksum(tmp_path: Path) -> None:
    store = CompositionReceiptStore(tmp_path / "r.json")
    store.save(_receipt(CompositionStatus.RESERVED))
    loaded = store.load()
    assert loaded.status_enum is CompositionStatus.RESERVED
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
    assert "context" in raw
    assert _CONTENT not in raw  # proposed content is not duplicated into the receipt
