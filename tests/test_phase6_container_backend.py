"""CP2 — container backend capability + fail-closed behavior (fake shell, no Docker)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.adapters.container_isolation import ContainerIsolationBackend
from ant_orchestrator.application.ports.test_isolation import (
    IsolatedExecutionSpec,
    IsolatedRunStatus,
    IsolationStatus,
)
from ant_orchestrator.application.ports.tool_errors import ToolNotFoundError
from ant_orchestrator.core.domain.test_failure import TestReasonCode
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.test_command_profile import (
    TestCommandKind,
    TestCommandProfile,
    TestCommandRegistry,
    TestCommandResolver,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.fake_shell import FakeShellAdapter, make_shell_result
from tests.support.phase3_harness import TS


def _resolver() -> TestCommandResolver:
    registry = TestCommandRegistry(
        (TestCommandProfile("probe.x", TestCommandKind.DIAGNOSTIC, ("python", "p.py"), 1),)
    )
    policy = CommandPolicy(
        (CommandRule("python", allowed_arg_prefixes=((),), allow_trailing_args=True),)
    )
    return TestCommandResolver(registry, policy)


def _backend(
    tmp_path: Path, shell: FakeShellAdapter, audit: FakeAuditSink
) -> ContainerIsolationBackend:
    (tmp_path / "snap").mkdir()
    (tmp_path / "rt").mkdir()
    return ContainerIsolationBackend(
        shell=shell,
        resolver=_resolver(),
        snapshot_root=tmp_path / "snap",
        runtime_root=tmp_path / "rt",
        audit_sink=audit,
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="ISO"),
    )


def _spec() -> IsolatedExecutionSpec:
    return IsolatedExecutionSpec(
        snapshot_ref="s1",
        runtime_output_ref="o1",
        command_profile_key="probe.x",
        timeout_ms=5000,
        max_processes=128,
    )


def _ran_docker_run(shell: FakeShellAdapter) -> bool:
    return any(r.argv[:2] == ("docker", "run") for r in shell.requests)


def test_capability_available_when_daemon_and_image_present(tmp_path: Path) -> None:
    shell = FakeShellAdapter(
        results=[make_shell_result(exit_code=0), make_shell_result(exit_code=0)]
    )
    cap = _backend(tmp_path, shell, FakeAuditSink()).capability()
    assert cap.status is IsolationStatus.AVAILABLE
    assert cap.backend_ref == "container"


def test_capability_cli_missing_is_unavailable(tmp_path: Path) -> None:
    shell = FakeShellAdapter(error=ToolNotFoundError(tool="shell", operation="resolve"))
    cap = _backend(tmp_path, shell, FakeAuditSink()).capability()
    assert cap.status is IsolationStatus.UNAVAILABLE
    assert cap.reason_code is TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE


def test_capability_daemon_unreachable_is_unavailable(tmp_path: Path) -> None:
    shell = FakeShellAdapter(results=[make_shell_result(exit_code=1)])
    cap = _backend(tmp_path, shell, FakeAuditSink()).capability()
    assert cap.status is IsolationStatus.UNAVAILABLE


def test_capability_image_missing_is_unavailable(tmp_path: Path) -> None:
    shell = FakeShellAdapter(
        results=[make_shell_result(exit_code=0), make_shell_result(exit_code=1)]
    )
    cap = _backend(tmp_path, shell, FakeAuditSink()).capability()
    assert cap.status is IsolationStatus.UNAVAILABLE


def test_run_fails_closed_without_host_execution(tmp_path: Path) -> None:
    # Image missing -> capability unavailable -> run must NOT execute on the host.
    shell = FakeShellAdapter(
        results=[make_shell_result(exit_code=0), make_shell_result(exit_code=1)]
    )
    result = _backend(tmp_path, shell, FakeAuditSink()).run(_spec())
    assert result.status is IsolatedRunStatus.ISOLATION_UNAVAILABLE
    assert not _ran_docker_run(shell)


def test_run_cli_missing_fails_closed(tmp_path: Path) -> None:
    shell = FakeShellAdapter(error=ToolNotFoundError(tool="shell", operation="resolve"))
    result = _backend(tmp_path, shell, FakeAuditSink()).run(_spec())
    assert result.status is IsolatedRunStatus.ISOLATION_UNAVAILABLE
    assert not _ran_docker_run(shell)


def test_capability_writes_audit_evidence(tmp_path: Path) -> None:
    audit = FakeAuditSink()
    shell = FakeShellAdapter(error=ToolNotFoundError(tool="shell", operation="resolve"))
    _backend(tmp_path, shell, audit).capability()
    assert audit.events
    assert all("backend" in e.detail for e in audit.events)
