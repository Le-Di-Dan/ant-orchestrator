"""CP6 context package builder tests: happy path, scope, secrets, budget, audit."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
)
from ant_orchestrator.application.ports.filesystem import (
    ContentRedaction,
    FileReadRequest,
    FileReadResult,
    FileSystemAdapter,
    FileWriteRequest,
    FileWriteResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import (
    ToolInvalidRequestError,
    ToolNotFoundError,
    ToolPermissionError,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import (
    ContextBuildFailure,
    ContextPackage,
    ContextPackageBuilder,
    is_secret_filename,
)
from ant_orchestrator.context.selection import ContextSelector, SelectionReason
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_INV = ToolInvocationMetadata(ToolKind.FILESYSTEM, "read_text")
_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "test-worker")


class FakeFs:
    """Fake FileSystemAdapter that serves pre-configured responses."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        self._files = files or {}
        self.read_calls: list[str] = []

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        self.read_calls.append(request.path)
        if request.path not in self._files:
            raise ToolNotFoundError(tool="fs", operation="read_text")
        content = self._files[request.path]
        redactions: tuple[ContentRedaction, ...] = ()
        if "DB_PASSWORD=" in content:
            redactions = (ContentRedaction(pattern="env_assignment", count=1),)
            content = content.replace("mysecret", "[REDACTED]")
        return FileReadResult(
            path=request.path, content=content, invocation=_INV, redactions=redactions
        )

    async def write_text(self, request: FileWriteRequest) -> FileWriteResult:
        raise NotImplementedError


class ScopeFs(FakeFs):
    """Raises ToolPermissionError for specific paths."""

    def __init__(self, files: dict[str, str], denied: set[str]) -> None:
        super().__init__(files)
        self._denied = denied

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        if request.path in self._denied:
            raise ToolPermissionError(tool="fs", operation="read_text")
        return await super().read_text(request)


class BinaryFs(FakeFs):
    """Raises ToolInvalidRequestError with detail_code for binary/oversized."""

    def __init__(self, detail_map: dict[str, str]) -> None:
        super().__init__({})
        self._details = detail_map

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        self.read_calls.append(request.path)
        if request.path in self._details:
            raise ToolInvalidRequestError(
                tool="fs",
                operation="read_text",
                detail_code=self._details[request.path],
            )
        raise ToolNotFoundError(tool="fs", operation="read_text")


def _builder(
    fs: FileSystemAdapter | None = None,
    audit: FakeAuditSink | None = None,
) -> tuple[ContextPackageBuilder, FakeAuditSink]:
    sink = audit or FakeAuditSink()
    return ContextPackageBuilder(
        fs=fs or FakeFs(),
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=sink,
        clock=FakeClock(_TS),
        id_gen=SequentialIdGenerator(),
    ), sink


def _req(
    *artifacts: tuple[str, ArtifactRequirement],
    excluded: tuple[str, ...] = (),
    budget: ContextBudget = _BUDGET,
) -> ContextBuildRequest:
    return ContextBuildRequest(
        task_id=TaskId("TASK-001"),
        consumer=_CONSUMER,
        requests=tuple(ArtifactRequest(p, r) for p, r in artifacts),
        excluded=excluded,
        budget=budget,
    )


def _run(b: ContextPackageBuilder, r: ContextBuildRequest) -> ContextPackage:
    return asyncio.get_event_loop().run_until_complete(b.build(r))


class TestHappyPath:
    def test_one_required(self) -> None:
        b, _ = _builder(FakeFs({"main.py": "hello world"}))
        pkg = _run(b, _req(("main.py", ArtifactRequirement.REQUIRED)))
        assert len(pkg.artifacts) == 1
        assert pkg.artifacts[0].content == "hello world"
        assert pkg.manifest.dispatchable is True

    def test_required_and_optional(self) -> None:
        b, _ = _builder(FakeFs({"a.py": "aaa", "b.py": "bbb"}))
        pkg = _run(
            b,
            _req(
                ("a.py", ArtifactRequirement.REQUIRED),
                ("b.py", ArtifactRequirement.OPTIONAL),
            ),
        )
        assert len(pkg.artifacts) == 2
        assert pkg.manifest.selected[0].reason is SelectionReason.REQUESTED_REQUIRED

    def test_stable_ordering(self) -> None:
        files = {f"{c}.py": c * 10 for c in "abcd"}
        b, _ = _builder(FakeFs(files))
        pkg = _run(b, _req(*((f"{c}.py", ArtifactRequirement.OPTIONAL) for c in "abcd")))
        assert [a.path for a in pkg.artifacts] == ["a.py", "b.py", "c.py", "d.py"]

    def test_empty_request_no_discovery(self) -> None:
        b, _ = _builder(FakeFs({"should_not.py": "x"}))
        pkg = _run(b, _req())
        assert len(pkg.artifacts) == 0
        assert pkg.manifest.dispatchable is True

    def test_unicode_content(self) -> None:
        b, _ = _builder(FakeFs({"u.py": "日本語テスト"}))
        pkg = _run(b, _req(("u.py", ArtifactRequirement.OPTIONAL)))
        assert "日本語" in pkg.artifacts[0].content

    def test_manifest_strategy_version(self) -> None:
        b, _ = _builder(FakeFs({"f.py": "x"}))
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        assert pkg.manifest.estimator_strategy == "character_heuristic"
        assert pkg.manifest.estimator_version == 1

    def test_manifest_consumer_typed(self) -> None:
        b, _ = _builder(FakeFs({"f.py": "x"}))
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        assert pkg.manifest.consumer.kind is ConsumerKind.WORKER

    def test_manifest_timestamp_from_clock(self) -> None:
        b, _ = _builder(FakeFs({"f.py": "x"}))
        pkg = _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))
        assert pkg.manifest.created_at == _TS


class TestScopeAndSecrets:
    def test_outside_scope_not_read(self) -> None:
        fs = ScopeFs({"ok.py": "ok"}, denied={"banned.py"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("ok.py", ArtifactRequirement.OPTIONAL),
                ("banned.py", ArtifactRequirement.OPTIONAL),
            ),
        )
        assert len(pkg.artifacts) == 1
        assert "banned.py" not in fs.read_calls

    def test_env_file_not_read(self) -> None:
        fs = FakeFs({"ok.py": "ok", ".env": "SECRET=x"})
        b, _ = _builder(fs)
        pkg = _run(
            b,
            _req(
                ("ok.py", ArtifactRequirement.OPTIONAL),
                (".env", ArtifactRequirement.OPTIONAL),
            ),
        )
        assert ".env" not in fs.read_calls
        rejected_paths = {r.path for r in pkg.manifest.rejected}
        assert ".env" in rejected_paths

    def test_env_local_not_read(self) -> None:
        fs = FakeFs({".env.local": "x"})
        b, _ = _builder(fs)
        _run(b, _req((".env.local", ArtifactRequirement.OPTIONAL)))
        assert ".env.local" not in fs.read_calls

    def test_pem_key_not_read(self) -> None:
        fs = FakeFs({"server.pem": "key"})
        b, _ = _builder(fs)
        _run(b, _req(("server.pem", ArtifactRequirement.OPTIONAL)))
        assert "server.pem" not in fs.read_calls

    def test_required_secret_sets_failure(self) -> None:
        fs = FakeFs({".env": "x"})
        b, _ = _builder(fs)
        pkg = _run(b, _req((".env", ArtifactRequirement.REQUIRED)))
        assert pkg.manifest.dispatchable is False

    def test_secret_content_redacted(self) -> None:
        fs = FakeFs({"cfg.py": "DB_PASSWORD=mysecret"})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("cfg.py", ArtifactRequirement.OPTIONAL)))
        assert "mysecret" not in pkg.artifacts[0].content
        assert len(pkg.manifest.redactions_applied) >= 1


class TestFileOutcomes:
    def test_binary_rejected(self) -> None:
        fs = BinaryFs({"bin.dat": "binary_content"})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("bin.dat", ArtifactRequirement.OPTIONAL)))
        assert len(pkg.manifest.rejected) == 1

    def test_oversized_rejected(self) -> None:
        fs = BinaryFs({"big.py": "oversized"})
        b, _ = _builder(fs)
        pkg = _run(b, _req(("big.py", ArtifactRequirement.OPTIONAL)))
        assert len(pkg.manifest.rejected) == 1

    def test_missing_file_rejected(self) -> None:
        b, _ = _builder(FakeFs({}))
        pkg = _run(b, _req(("missing.py", ArtifactRequirement.OPTIONAL)))
        assert len(pkg.manifest.rejected) == 1

    def test_infrastructure_failure_raises(self) -> None:
        from ant_orchestrator.application.ports.tool_errors import ToolExecutionError

        class _FailFs(FakeFs):
            async def read_text(self, request: FileReadRequest) -> FileReadResult:
                raise ToolExecutionError(tool="fs", operation="read_text")

        b, _ = _builder(_FailFs())
        with pytest.raises(ContextBuildFailure):
            _run(b, _req(("f.py", ArtifactRequirement.OPTIONAL)))


class TestSecretFilenamePolicy:
    @pytest.mark.parametrize(
        "path",
        [
            ".env",
            ".env.local",
            ".env.production",
            "config/.env",
            "server.pem",
            "id_rsa",
            "id_ed25519",
            "keys/server.key",
            "secrets.json",
            "credentials.yaml",
        ],
    )
    def test_secret_filenames_detected(self, path: str) -> None:
        assert is_secret_filename(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "main.py",
            "src/app.py",
            "environment.py",
            "test_env.py",
            "README.md",
            "config.yaml",
        ],
    )
    def test_normal_filenames_allowed(self, path: str) -> None:
        assert is_secret_filename(path) is False
