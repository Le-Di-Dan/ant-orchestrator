"""Scriptable FakeShellAdapter test double (CP5). Runs no real process."""

from __future__ import annotations

from ant_orchestrator.application.ports.shell import ShellRequest, ShellResult
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


def make_shell_result(
    *, exit_code: int = 0, stdout: str = "", stderr: str = "", duration_seconds: float = 0.0
) -> ShellResult:
    """Build a ShellResult for scripting fakes/tests."""
    return ShellResult(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_seconds=duration_seconds,
        invocation=ToolInvocationMetadata(tool=ToolKind.SHELL, operation="run"),
    )


class FakeShellAdapter:
    """Returns scripted results or raises a scripted error; runs no subprocess."""

    def __init__(
        self,
        *,
        results: list[ShellResult] | None = None,
        error: ToolAdapterError | None = None,
    ) -> None:
        self._results = list(results) if results is not None else []
        self._error = error
        self.requests: list[ShellRequest] = []

    async def run(self, request: ShellRequest) -> ShellResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._results:
            return self._results.pop(0)
        return make_shell_result()
