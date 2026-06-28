"""Phase 7 CP4 — digest, store persist/verify/load, and regression tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
)
from ant_orchestrator.application.ports.memory_context import (
    MemoryContextEntry,
    MemoryFilterManifest,
    combined_rendered_text,
)
from ant_orchestrator.context.digest import (
    canonical_context_manifest,
    manifest_digest,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.memory import MemoryContextSection, MemoryRecordManifest
from ant_orchestrator.context.package import (
    ContextManifest,
    ContextPackage,
    ContextPackageBuilder,
)
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import (
    ContextPackageStore,
    SourceDigestMismatch,
)
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "test-worker")
_EST = CharacterHeuristicEstimator(divisor=4)


def _filter() -> MemoryFilterManifest:
    return MemoryFilterManifest(
        task_id=None,
        memory_type=None,
        source=None,
        confidence=None,
        tags=(),
        include_deprecated=False,
        resolved_limit=20,
    )


def _entry(record_id: str = "M-1", title: str = "T", summary: str = "S") -> MemoryContextEntry:
    return MemoryContextEntry(
        record_id=record_id,
        type_value="project_fact",
        task_id_value=None,
        source="ci",
        confidence_value="high",
        title=title,
        summary=summary,
        tags=("alpha", "beta"),
    )


def _empty_manifest() -> ContextManifest:
    from ant_orchestrator.context.budget import BudgetUsage

    return ContextManifest(
        task_id="T-1",
        consumer=_CONSUMER,
        selected=(),
        rejected=(),
        budget_initial=_BUDGET,
        budget_used=BudgetUsage(tokens=0, files=0),
        budget_remaining=BudgetUsage(tokens=10000, files=10),
        redactions_applied=(),
        any_truncated=False,
        estimator_strategy="character_heuristic",
        estimator_version=1,
        policy_version=1,
        created_at=_TS,
        dispatchable=True,
    )


def _package_with_memory(*entries: MemoryContextEntry) -> ContextPackage:
    consumed = sum(_EST.estimate(e.rendered_text()).value for e in entries)
    records = tuple(MemoryRecordManifest(e.record_id, e.type_value) for e in entries)
    section = MemoryContextSection(
        applied_filter=_filter(),
        records=records,
        returned_count=len(records),
        budget_consumed_tokens=consumed,
    )
    from ant_orchestrator.context.budget import BudgetUsage

    manifest = ContextManifest(
        task_id="T-1",
        consumer=_CONSUMER,
        selected=(),
        rejected=(),
        budget_initial=_BUDGET,
        budget_used=BudgetUsage(tokens=0, files=0),
        budget_remaining=BudgetUsage(tokens=10000, files=10),
        redactions_applied=(),
        any_truncated=False,
        estimator_strategy="character_heuristic",
        estimator_version=1,
        policy_version=1,
        created_at=_TS,
        dispatchable=True,
        memory_section=section if entries else None,
    )
    return ContextPackage(manifest=manifest, artifacts=(), memory_entries=entries)


def _package_no_memory() -> ContextPackage:
    return ContextPackage(manifest=_empty_manifest(), artifacts=())


# ---------------------------------------------------------------------------
# Digest — determinism
# ---------------------------------------------------------------------------


def test_same_package_same_digest() -> None:
    pkg = _package_with_memory(_entry())
    c1 = canonical_context_manifest(pkg)
    c2 = canonical_context_manifest(pkg)
    assert manifest_digest(c1) == manifest_digest(c2)


def test_field_change_changes_digest() -> None:
    d1 = manifest_digest(canonical_context_manifest(_package_with_memory(_entry(summary="orig"))))
    d2 = manifest_digest(canonical_context_manifest(_package_with_memory(_entry(summary="new"))))
    assert d1 != d2


def test_entry_order_AB_differs_from_BA() -> None:
    a = _entry("M-A", title="Alpha")
    b = _entry("M-B", title="Beta")
    d_ab = manifest_digest(canonical_context_manifest(_package_with_memory(a, b)))
    d_ba = manifest_digest(canonical_context_manifest(_package_with_memory(b, a)))
    assert d_ab != d_ba


def test_pre_sorted_tags_produce_same_digest() -> None:
    e1 = MemoryContextEntry("M-1", "project_fact", None, "ci", "high", "T", "S", ("a", "b"))
    e2 = MemoryContextEntry("M-1", "project_fact", None, "ci", "high", "T", "S", ("a", "b"))
    d1 = manifest_digest(canonical_context_manifest(_package_with_memory(e1)))
    d2 = manifest_digest(canonical_context_manifest(_package_with_memory(e2)))
    assert d1 == d2


def test_add_entry_changes_digest() -> None:
    d1 = manifest_digest(canonical_context_manifest(_package_with_memory(_entry("M-1"))))
    d2 = manifest_digest(
        canonical_context_manifest(_package_with_memory(_entry("M-1"), _entry("M-2")))
    )
    assert d1 != d2


def test_remove_entry_changes_digest() -> None:
    d1 = manifest_digest(canonical_context_manifest(_package_with_memory(_entry())))
    d2 = manifest_digest(canonical_context_manifest(_package_no_memory()))
    assert d1 != d2


def test_memory_free_package_digest_stable() -> None:
    pkg = _package_no_memory()
    c = canonical_context_manifest(pkg)
    assert c["memory_entries"] == []
    assert manifest_digest(c) == manifest_digest(c)


# ---------------------------------------------------------------------------
# Store — memory source written and loaded
# ---------------------------------------------------------------------------


def test_store_memory_source_written(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    e = _entry()
    pkg = _package_with_memory(e)
    ctx = store.persist("run-1", "action-1", pkg)
    target = (tmp_path / "artifacts") / ctx.context_package_ref
    mem_file = target / "sources" / "memory_context.txt"
    assert mem_file.exists()
    assert e.rendered_text() in mem_file.read_text(encoding="utf-8")


def test_store_memory_exact_combined_content(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    e1 = _entry("M-1", title="First")
    e2 = _entry("M-2", title="Second")
    pkg = _package_with_memory(e1, e2)
    ctx = store.persist("run-1", "action-1", pkg)
    target = (tmp_path / "artifacts") / ctx.context_package_ref
    actual = (target / "sources" / "memory_context.txt").read_text(encoding="utf-8")
    assert actual == combined_rendered_text((e1, e2))


def test_store_load_returns_memory_source(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    e = _entry(summary="Useful fact.")
    pkg = _package_with_memory(e)
    ctx = store.persist("run-1", "action-1", pkg)
    sources = store.load(ctx.context_package_ref, ctx.manifest_digest)
    paths = {s.path for s in sources}
    assert "memory://ant/context" in paths
    mem_src = next(s for s in sources if s.path == "memory://ant/context")
    assert e.rendered_text() in mem_src.content


def test_store_memory_source_ordering_stable(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    e1 = _entry("M-1", title="Alpha")
    e2 = _entry("M-2", title="Beta")
    pkg = _package_with_memory(e1, e2)
    ctx = store.persist("run-1", "action-1", pkg)
    sources = store.load(ctx.context_package_ref, ctx.manifest_digest)
    mem = next(s for s in sources if s.path == "memory://ant/context")
    assert mem.content.index("Alpha") < mem.content.index("Beta")


def test_store_tamper_memory_content_raises(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    pkg = _package_with_memory(_entry())
    ctx = store.persist("run-1", "action-1", pkg)
    target = (tmp_path / "artifacts") / ctx.context_package_ref
    (target / "sources" / "memory_context.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(SourceDigestMismatch):
        store.load(ctx.context_package_ref, ctx.manifest_digest)


def test_store_missing_memory_file_raises(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    pkg = _package_with_memory(_entry())
    ctx = store.persist("run-1", "action-1", pkg)
    target = (tmp_path / "artifacts") / ctx.context_package_ref
    (target / "sources" / "memory_context.txt").unlink()
    from ant_orchestrator.context.store import ContextArtifactCorrupt

    with pytest.raises(ContextArtifactCorrupt):
        store.load(ctx.context_package_ref, ctx.manifest_digest)


def test_store_legacy_no_memory_package_still_works(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    pkg = _package_no_memory()
    ctx = store.persist("run-1", "action-1", pkg)
    sources = store.load(ctx.context_package_ref, ctx.manifest_digest)
    assert "memory://ant/context" not in {s.path for s in sources}


def test_store_empty_selection_does_not_write_memory_file(tmp_path: Path) -> None:
    store = ContextPackageStore(tmp_path / "artifacts")
    pkg = _package_no_memory()
    ctx = store.persist("run-1", "action-1", pkg)
    target = (tmp_path / "artifacts") / ctx.context_package_ref
    assert not (target / "sources" / "memory_context.txt").exists()


# ---------------------------------------------------------------------------
# Regression — backward compat without memory_selection
# ---------------------------------------------------------------------------


def test_context_package_builder_still_builds_without_memory() -> None:
    from ant_orchestrator.application.ports.filesystem import FileReadRequest, FileWriteRequest
    from ant_orchestrator.application.ports.tool_errors import ToolNotFoundError

    class _FakeFs:
        async def read_text(self, req: FileReadRequest) -> None:
            raise ToolNotFoundError(tool="fs", operation="read_text")

        async def write_text(self, req: FileWriteRequest) -> None:
            raise NotImplementedError

    builder = ContextPackageBuilder(
        fs=_FakeFs(),
        estimator=_EST,
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(_TS),
        id_gen=SequentialIdGenerator(),
    )
    request = ContextBuildRequest(
        task_id=TaskId("T-1"),
        consumer=_CONSUMER,
        requests=(),
        excluded=(),
        budget=_BUDGET,
    )
    loop = asyncio.new_event_loop()
    try:
        pkg = loop.run_until_complete(builder.build(request))
    finally:
        loop.close()
    assert pkg.memory_entries == ()
    assert pkg.manifest.memory_section is None


def test_import_boundary_memory_context_port() -> None:
    import ast

    import ant_orchestrator

    pkg = Path(ant_orchestrator.__file__).parent
    f = pkg / "application" / "ports" / "memory_context.py"
    tree = ast.parse(f.read_text(encoding="utf-8"))
    modules = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    for mod in modules:
        assert not mod.startswith("ant_orchestrator.context"), mod
        assert not mod.startswith("ant_orchestrator.persistence"), mod
