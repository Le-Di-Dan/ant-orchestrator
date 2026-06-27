"""CP2 tests — immutable context preparation, digest binding, anti-TOCTOU verify.

Covers (A) preparation happy path + proposal binding + context_node promotion,
(B) digest determinism, (C) scope / no-scan, (D) tampering/missing/corrupt fail
closed, and (E) state schema bump + JSON-safety. Uses the existing context builder
fakes plus a real ``ContextPackageStore`` over a temporary workspace root.
"""

from __future__ import annotations

import asyncio
import json
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
    ContextScopeViolation,
)
from ant_orchestrator.application.ports.document_worker import DocumentationTask, DocumentOperation
from ant_orchestrator.application.services.context_preparation import (
    ContextPreparationService,
    ProposalDraftInput,
)
from ant_orchestrator.config.constants import GRAPH_STATE_SCHEMA_VERSION
from ant_orchestrator.context.digest import (
    canonical_context_manifest,
    manifest_digest,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackage, ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import (
    ContextArtifactCorrupt,
    ContextIdentityConflict,
    ContextPackageMissing,
    ContextPackageStore,
    ManifestDigestMismatch,
    SourceDigestMismatch,
)
from ant_orchestrator.core.domain.value_objects import TaskId, TokenCount, UtcTimestamp
from ant_orchestrator.workflows.nodes import PHASE_EXECUTE, context_node
from ant_orchestrator.workflows.state import (
    SchemaCompatibility,
    assert_json_safe,
    check_schema_version,
    new_graph_state,
    round_trip,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.test_context_package import FakeFs, ScopeFs

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")


def _await(coro: object) -> object:
    """Run a coroutine on a private loop (never disturbs the shared event loop)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)  # type: ignore[arg-type]
    finally:
        loop.close()


def _builder(
    files: dict[str, str], fs: FakeFs | None = None
) -> tuple[ContextPackageBuilder, FakeFs]:
    adapter = fs if fs is not None else FakeFs(files)
    builder = ContextPackageBuilder(
        fs=adapter,
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(_TS),
        id_gen=SequentialIdGenerator(),
    )
    return builder, adapter


def _build(files: dict[str, str], inputs: tuple[str, ...]) -> ContextPackage:
    builder, _ = _builder(files)
    request = ContextBuildRequest(
        task_id=TaskId("act-1"),
        consumer=_CONSUMER,
        requests=tuple(ArtifactRequest(p, ArtifactRequirement.REQUIRED) for p in inputs),
        excluded=(),
        budget=_BUDGET,
    )
    return _await(builder.build(request))


def _task(inputs: tuple[str, ...] = ("docs/source/brief.md",)) -> DocumentationTask:
    return DocumentationTask(
        logical_action_id="act-1",
        operation=DocumentOperation.CREATE,
        target_document="handoff",
        instruction_summary="write a handoff",
        required_sections=("Summary",),
        approved_inputs=inputs,
    )


def _service(
    files: dict[str, str], root: Path, fs: FakeFs | None = None
) -> ContextPreparationService:
    builder, adapter = _builder(files, fs)
    preparer = ContextSourcePreparerImpl(builder, ContextPackageStore(root))
    return ContextPreparationService(preparer)


def _draft(task: DocumentationTask) -> ProposalDraftInput:
    return ProposalDraftInput(
        run_id="run-1",
        task=task,
        candidate_target="docs/handoffs/HANDOFF-001.md",
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        protected_policy_version=1,
        energy_estimate=TokenCount(1000),
        expected_mutation="create docs/handoffs/HANDOFF-001.md",
        proposal_version=1,
        consumer=_CONSUMER,
        budget=_BUDGET,
    )


# --- A. preparation happy path + binding + context_node --------------------


def test_prepare_binds_context_into_proposal(tmp_path: Path) -> None:
    service = _service({"docs/source/brief.md": "hello"}, tmp_path)
    result = _await(service.prepare(_draft(_task())))
    assert result.context_package_ref
    assert result.manifest_digest
    assert result.proposal.context_package_ref == result.context_package_ref
    assert result.proposal.manifest_digest == result.manifest_digest
    # The persisted package verifies against the bound digest.
    ContextPackageStore(tmp_path).verify(result.context_package_ref, result.manifest_digest)


def test_proposal_digest_changes_with_manifest_digest(tmp_path: Path) -> None:
    a = _await(_service({"docs/source/brief.md": "one"}, tmp_path).prepare(_draft(_task())))
    b = _await(
        _service({"docs/source/brief.md": "two"}, tmp_path / "other").prepare(_draft(_task()))
    )
    assert a.manifest_digest != b.manifest_digest
    assert a.proposal.proposal_digest() != b.proposal.proposal_digest()


def test_context_node_promotes_prepared_refs() -> None:
    delta = context_node(
        {"workflow_run_id": "run-1", "context_package_ref": "ref-1", "manifest_digest": "d" * 64}
    )
    assert delta["context_package_ref"] == "ref-1"
    assert delta["manifest_digest"] == "d" * 64
    assert delta["context_ref"] == "ref-1"  # no placeholder
    assert not str(delta["context_ref"]).startswith("ctx:")
    assert delta["phase"] == PHASE_EXECUTE


def test_context_node_legacy_path_without_prepared_context() -> None:
    delta = context_node({"workflow_run_id": "run-1", "plan": {"plan_revision": 0}})
    assert delta["context_ref"] == "ctx:run-1:0"
    assert "manifest_digest" not in delta


# --- B. digest determinism -------------------------------------------------


def test_digest_independent_of_source_order(tmp_path: Path) -> None:
    pkg = _build({"a.md": "aaa", "b.md": "bbb"}, ("a.md", "b.md"))
    reordered = ContextPackage(manifest=pkg.manifest, artifacts=tuple(reversed(pkg.artifacts)))
    assert manifest_digest(canonical_context_manifest(pkg)) == manifest_digest(
        canonical_context_manifest(reordered)
    )


def test_digest_independent_of_workspace_root(tmp_path: Path) -> None:
    pkg = _build({"docs/source/brief.md": "same"}, ("docs/source/brief.md",))
    one = ContextPackageStore(tmp_path / "a").persist("run-1", "act-1", pkg)
    two = ContextPackageStore(tmp_path / "b").persist("run-1", "act-1", pkg)
    assert one.manifest_digest == two.manifest_digest


def test_digest_sensitive_to_content_and_path() -> None:
    base = manifest_digest(canonical_context_manifest(_build({"a.md": "x"}, ("a.md",))))
    changed_content = manifest_digest(canonical_context_manifest(_build({"a.md": "y"}, ("a.md",))))
    changed_path = manifest_digest(canonical_context_manifest(_build({"b.md": "x"}, ("b.md",))))
    assert base != changed_content
    assert base != changed_path


def test_digest_sensitive_to_source_set_and_schema() -> None:
    one = canonical_context_manifest(_build({"a.md": "x"}, ("a.md",)))
    two = canonical_context_manifest(_build({"a.md": "x", "b.md": "y"}, ("a.md", "b.md")))
    assert manifest_digest(one) != manifest_digest(two)
    bumped = dict(one)
    bumped["manifest_schema_version"] = 999
    assert manifest_digest(bumped) != manifest_digest(one)


# --- C. scope / no-scan ----------------------------------------------------


def test_required_input_outside_scope_fails_closed(tmp_path: Path) -> None:
    fs = ScopeFs({"docs/source/brief.md": "ok"}, denied={"docs/source/brief.md"})
    service = _service({}, tmp_path, fs=fs)
    with pytest.raises(ContextScopeViolation):
        _await(service.prepare(_draft(_task())))


def test_required_secret_input_fails_closed(tmp_path: Path) -> None:
    service = _service({".env": "SECRET=x"}, tmp_path)
    with pytest.raises(ContextScopeViolation):
        _await(service.prepare(_draft(_task((".env",)))))


def test_preparer_reads_only_approved_inputs(tmp_path: Path) -> None:
    fs = FakeFs({"docs/source/brief.md": "ok", "docs/source/other.md": "nope"})
    service = _service({}, tmp_path, fs=fs)
    _await(service.prepare(_draft(_task())))
    assert fs.read_calls == ["docs/source/brief.md"]


# --- D. anti-TOCTOU / tampering --------------------------------------------


def _persist(tmp_path: Path) -> tuple[ContextPackageStore, str, str]:
    store = ContextPackageStore(tmp_path)
    persisted = store.persist("run-1", "act-1", _build({"a.md": "content"}, ("a.md",)))
    return store, persisted.context_package_ref, persisted.manifest_digest


def test_verify_passes_for_intact_package(tmp_path: Path) -> None:
    store, ref, digest = _persist(tmp_path)
    store.verify(ref, digest)  # no raise


def test_tampered_manifest_fails_closed(tmp_path: Path) -> None:
    store, ref, digest = _persist(tmp_path)
    manifest_path = (tmp_path / ref) / "manifest.json"
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document["canonical"]["task_id"] = "tampered"
    manifest_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ContextArtifactCorrupt):
        store.verify(ref, digest)


def test_tampered_source_fails_closed(tmp_path: Path) -> None:
    store, ref, digest = _persist(tmp_path)
    source = (tmp_path / ref) / "sources" / "0000.txt"
    source.write_text("mutated", encoding="utf-8")
    with pytest.raises(SourceDigestMismatch):
        store.verify(ref, digest)


def test_missing_package_fails_closed(tmp_path: Path) -> None:
    store, ref, digest = _persist(tmp_path)
    store.verify(ref, digest)
    other = ContextPackageStore(tmp_path / "empty")
    with pytest.raises(ContextPackageMissing):
        other.verify(ref, digest)


def test_expected_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    store, ref, _ = _persist(tmp_path)
    with pytest.raises(ManifestDigestMismatch):
        store.verify(ref, "f" * 64)


def test_malformed_manifest_fails_closed(tmp_path: Path) -> None:
    store, ref, digest = _persist(tmp_path)
    ((tmp_path / ref) / "manifest.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ContextArtifactCorrupt):
        store.verify(ref, digest)


def test_same_identity_different_digest_conflicts(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path)
    store.persist("run-1", "act-1", _build({"a.md": "one"}, ("a.md",)))
    with pytest.raises(ContextIdentityConflict):
        store.persist("run-1", "act-1", _build({"a.md": "two"}, ("a.md",)))


def test_same_identity_same_digest_reuses(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path)
    first = store.persist("run-1", "act-1", _build({"a.md": "one"}, ("a.md",)))
    second = store.persist("run-1", "act-1", _build({"a.md": "one"}, ("a.md",)))
    assert first == second


def test_reference_escaping_artifact_root_fails_closed(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path)
    with pytest.raises(ContextArtifactCorrupt):
        store.verify("../../etc/passwd", "d" * 64)


# --- E. state schema bump + JSON-safety ------------------------------------


def test_schema_version_bumped_to_two() -> None:
    assert GRAPH_STATE_SCHEMA_VERSION == 2
    state = new_graph_state(task_id="t", workflow_run_id="r", base_retry_limit=2)
    assert state["graph_state_schema_version"] == 2
    assert check_schema_version(state) is SchemaCompatibility.COMPATIBLE


def test_pre_cp2_schema_is_unknown() -> None:
    legacy = new_graph_state(task_id="t", workflow_run_id="r", base_retry_limit=2)
    legacy["graph_state_schema_version"] = 1
    assert check_schema_version(legacy) is SchemaCompatibility.UNKNOWN_VERSION


def test_promoted_context_state_is_json_safe() -> None:
    state = new_graph_state(task_id="t", workflow_run_id="r", base_retry_limit=2)
    promoted = context_node(
        {"workflow_run_id": "r", "context_package_ref": "ref", "manifest_digest": "d"}
    )
    state.update(promoted)
    assert_json_safe(state)
    assert round_trip(state)["manifest_digest"] == "d"
