"""FakeShellAdapter contract conformance + fake-specific tests (CP5)."""

from __future__ import annotations

import asyncio

import pytest

from ant_orchestrator.application.ports.shell import ShellAdapter, ShellRequest
from ant_orchestrator.application.ports.tool_errors import (
    ToolAdapterError,
    ToolNotFoundError,
    ToolTimeoutError,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from tests.contracts.shell_contract import ShellContract
from tests.support.fake_shell import FakeShellAdapter, make_shell_result


class TestFakeShellContract(ShellContract):
    def build_success_adapter(self) -> ShellAdapter:
        return FakeShellAdapter(results=[make_shell_result(exit_code=0, stdout="out")])

    def build_nonzero_adapter(self) -> ShellAdapter:
        return FakeShellAdapter(results=[make_shell_result(exit_code=1, stderr="boom")])

    def build_error_adapter(self, error: ToolAdapterError) -> ShellAdapter:
        return FakeShellAdapter(error=error)


def test_streams_preserved() -> None:
    adapter = FakeShellAdapter(results=[make_shell_result(exit_code=2, stdout="o", stderr="e")])
    result = asyncio.run(adapter.run(ShellRequest(argv=("x",))))
    assert (result.exit_code, result.stdout, result.stderr) == (2, "o", "e")


def test_fake_records_requests() -> None:
    adapter = FakeShellAdapter()
    request = ShellRequest(argv=("ls", "-la"))
    asyncio.run(adapter.run(request))
    assert adapter.requests == [request]


def test_executable_not_found_simulation() -> None:
    adapter = FakeShellAdapter(error=ToolNotFoundError(tool="shell"))
    with pytest.raises(ToolNotFoundError):
        asyncio.run(adapter.run(ShellRequest(argv=("missing",))))


def test_timeout_simulation_is_retryable() -> None:
    adapter = FakeShellAdapter(error=ToolTimeoutError(tool="shell"))
    with pytest.raises(ToolTimeoutError) as info:
        asyncio.run(adapter.run(ShellRequest(argv=("sleep",))))
    assert info.value.retryable is True


def test_empty_argv_rejected() -> None:
    with pytest.raises(InvariantViolation):
        ShellRequest(argv=())


@pytest.mark.parametrize("bad_executable", ["", "   "])
def test_empty_or_whitespace_executable_rejected(bad_executable: str) -> None:
    with pytest.raises(InvariantViolation):
        ShellRequest(argv=(bad_executable,))


def test_non_string_argument_rejected() -> None:
    with pytest.raises(InvariantViolation):
        ShellRequest(argv=("tool", 123))  # type: ignore[arg-type]


def test_empty_and_whitespace_arguments_after_executable_preserved() -> None:
    adapter = FakeShellAdapter()
    request = ShellRequest(argv=("python", "script.py", "", " ", "value with spaces"))
    asyncio.run(adapter.run(request))
    assert adapter.requests[0].argv == ("python", "script.py", "", " ", "value with spaces")


def test_negative_timeout_rejected() -> None:
    with pytest.raises(InvariantViolation):
        ShellRequest(argv=("x",), timeout_seconds=0)
