"""CP6 manifest consistency, budget, dedup, audit, and architecture tests."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.audit import AuditEventType
from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
)
from ant_orchestrator.application.ports.filesystem import (
    FileReadRequest,
    FileReadResult,
    FileWriteRequest,
    FileWriteResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolNotFoundError
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackage, ContextPackageBuilder
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_INV = ToolInvocationMetadata(ToolKind.FILESYSTEM, "read_text")
_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "w1")


class _FakeFs:
    def __init__(self, files: dict[str, str]) -> None:
        self._files = files
        self.read_calls: list[str] = []

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        self.read_calls.append(request.path)
        if request.path not in self._files:
            raise ToolNotFoundError(tool="fs", operation="read_text")
        return FileReadResult(
            path=request.path,
            content=self._files[request.path],
            invocation=_INV,
            redactions=(),
        )

    async def write_text(self, request: FileWriteRequest) -> FileWriteResult:
        raise NotImplementedError


def _builder(
    fs: _FakeFs,
    audit: FakeAuditSink | None = None,
) -> tuple[ContextPackageBuilder, FakeAuditSink]:
    sink = audit or FakeAuditSink()
    return ContextPackageBuilder(
        fs=fs,
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=sink,
        clock=FakeClock(_TS),
        id_gen=SequentialIdGenerator(),
    ), sink


def _req(
    *arts: tuple[str, ArtifactRequirement],
    excluded: tuple[str, ...] = (),
    budget: ContextBudget | None = None,
) -> ContextBuildRequest:
    return ContextBuildRequest(
        task_id=TaskId("T-1"),
        consumer=_CONSUMER,
        requests=tuple(ArtifactRequest(p, r) for p, r in arts),
        excluded=excluded,
        budget=budget or ContextBudget(10000, 10, 5000),
    )


def _run(b: ContextPackageBuilder, r: ContextBuildRequest) -> ContextPackage:
    return asyncio.get_event_loop().run_until_complete(b.build(r))


class TestManifestConsistency:
    def test_selected_equals_artifacts(self) -> None:
        fs = _FakeFs({"a.py": "aaa", "b.py": "bbb"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("a.py", ArtifactRequirement.REQUIRED),
                ("b.py", ArtifactRequirement.OPTIONAL),
            ),
        )
        assert len(pkg.manifest.selected) == len(pkg.artifacts)
        assert [s.path for s in pkg.manifest.selected] == [a.path for a in pkg.artifacts]

    def test_token_totals_match(self) -> None:
        fs = _FakeFs({"a.py": "x" * 40, "b.py": "y" * 80})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("a.py", ArtifactRequirement.OPTIONAL),
                ("b.py", ArtifactRequirement.OPTIONAL),
            ),
        )
        total = sum(a.estimated_tokens.value for a in pkg.artifacts)
        assert pkg.manifest.budget_used.tokens == total

    def test_remaining_correct(self) -> None:
        budget = ContextBudget(1000, 10, 500)
        fs = _FakeFs({"f.py": "x" * 100})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL), budget=budget))
        assert pkg.manifest.budget_remaining.tokens == 1000 - pkg.manifest.budget_used.tokens
        assert pkg.manifest.budget_remaining.files == 9

    def test_dispatchable_true_no_failure(self) -> None:
        fs = _FakeFs({"f.py": "ok"})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.REQUIRED)))
        assert pkg.manifest.dispatchable is True

    def test_immutable_manifest(self) -> None:
        fs = _FakeFs({"f.py": "x"})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        with pytest.raises(AttributeError):
            pkg.manifest.dispatchable = False  # type: ignore[misc]


class TestBudgetEnforcement:
    def test_exact_total_budget(self) -> None:
        budget = ContextBudget(10, 5, 10)
        fs = _FakeFs({"f.py": "x" * 40})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL), budget=budget))
        assert len(pkg.artifacts) == 1

    def test_total_budget_exceeded(self) -> None:
        budget = ContextBudget(5, 5, 5)
        fs = _FakeFs({"f.py": "x" * 40})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL), budget=budget))
        assert len(pkg.artifacts) == 0

    def test_per_file_exceeded(self) -> None:
        budget = ContextBudget(10000, 5, 5)
        fs = _FakeFs({"f.py": "x" * 40})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL), budget=budget))
        assert len(pkg.artifacts) == 0

    def test_max_files_exceeded(self) -> None:
        budget = ContextBudget(10000, 1, 5000)
        fs = _FakeFs({"a.py": "a", "b.py": "b"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("a.py", ArtifactRequirement.OPTIONAL),
                ("b.py", ArtifactRequirement.OPTIONAL),
                budget=budget,
            ),
        )
        assert len(pkg.artifacts) == 1

    def test_required_over_budget_non_dispatchable(self) -> None:
        budget = ContextBudget(5, 5, 5)
        fs = _FakeFs({"f.py": "x" * 40})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.REQUIRED), budget=budget))
        assert pkg.manifest.dispatchable is False
        assert len(pkg.manifest.rejected) == 1

    def test_optional_over_budget_still_dispatchable(self) -> None:
        budget = ContextBudget(5, 5, 5)
        fs = _FakeFs({"f.py": "x" * 40})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL), budget=budget))
        assert pkg.manifest.dispatchable is True


class TestDuplicateExclusion:
    def test_duplicate_optional_read_once(self) -> None:
        fs = _FakeFs({"f.py": "data"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("f.py", ArtifactRequirement.OPTIONAL),
                ("f.py", ArtifactRequirement.OPTIONAL),
            ),
        )
        assert len(pkg.artifacts) == 1
        assert fs.read_calls.count("f.py") == 1

    def test_required_dominates_optional(self) -> None:
        fs = _FakeFs({"f.py": "data"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("f.py", ArtifactRequirement.OPTIONAL),
                ("f.py", ArtifactRequirement.REQUIRED),
            ),
        )
        assert len(pkg.artifacts) == 1

    def test_explicit_exclusion_optional(self) -> None:
        fs = _FakeFs({"f.py": "data"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("f.py", ArtifactRequirement.OPTIONAL),
                excluded=("f.py",),
            ),
        )
        assert len(pkg.artifacts) == 0
        assert "f.py" not in fs.read_calls

    def test_explicit_exclusion_required(self) -> None:
        fs = _FakeFs({"f.py": "data"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("f.py", ArtifactRequirement.REQUIRED),
                excluded=("f.py",),
            ),
        )
        assert pkg.manifest.dispatchable is False


class TestAudit:
    def test_context_build_event_emitted(self) -> None:
        fs = _FakeFs({"f.py": "x"})
        b, sink = _builder(fs)
        _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        build_events = [e for e in sink.events if e.event_type is AuditEventType.CONTEXT_BUILD]
        assert len(build_events) == 1

    def test_audit_no_content(self) -> None:
        fs = _FakeFs({"f.py": "sensitive data xyz"})
        b, sink = _builder(fs)
        _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        for e in sink.events:
            for v in e.detail.values():
                assert "sensitive" not in v
                assert "xyz" not in v

    def test_audit_shows_dispatchable(self) -> None:
        fs = _FakeFs({"f.py": "x"})
        b, sink = _builder(fs)
        _run(b, _req(("f.py", ArtifactRequirement.REQUIRED)))
        build = [e for e in sink.events if e.event_type is AuditEventType.CONTEXT_BUILD][0]
        assert build.detail["dispatchable"] == "True"

    def test_audit_failure_prevents_return(self) -> None:
        class _FailSink(FakeAuditSink):
            def write(self, event: object) -> None:
                if getattr(event, "event_type", None) is AuditEventType.CONTEXT_BUILD:
                    raise RuntimeError("audit fail")

        fs = _FakeFs({"f.py": "x"})
        b, _ = _builder(fs, audit=_FailSink())
        with pytest.raises(RuntimeError):
            _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))

    def test_works_with_fake_audit_sink(self) -> None:
        fs = _FakeFs({"f.py": "ok"})
        b, sink = _builder(fs)
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        assert len(sink.events) >= 1
        assert pkg.manifest.dispatchable is True
