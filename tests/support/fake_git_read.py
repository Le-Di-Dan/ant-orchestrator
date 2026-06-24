"""Scriptable FakeGitReadAdapter test double (CP5). Runs no real git, reads no .git."""

from __future__ import annotations

from ant_orchestrator.application.ports.git_read import (
    GitDiffRequest,
    GitDiffResult,
    GitStatusRequest,
    GitStatusResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


def _meta(operation: str) -> ToolInvocationMetadata:
    return ToolInvocationMetadata(tool=ToolKind.GIT, operation=operation)


class FakeGitReadAdapter:
    """Returns scripted status/diff or raises a scripted error; never runs git."""

    def __init__(
        self,
        *,
        status_result: GitStatusResult | None = None,
        diff_result: GitDiffResult | None = None,
        error: ToolAdapterError | None = None,
    ) -> None:
        self._status_result = status_result
        self._diff_result = diff_result
        self._error = error
        self.status_requests: list[GitStatusRequest] = []
        self.diff_requests: list[GitDiffRequest] = []

    async def status(self, request: GitStatusRequest) -> GitStatusResult:
        self.status_requests.append(request)
        if self._error is not None:
            raise self._error
        if self._status_result is not None:
            return self._status_result
        return GitStatusResult(entries=(), is_clean=True, invocation=_meta("status"))

    async def diff(self, request: GitDiffRequest) -> GitDiffResult:
        self.diff_requests.append(request)
        if self._error is not None:
            raise self._error
        if self._diff_result is not None:
            return self._diff_result
        return GitDiffResult(changes=(), diff_text="", invocation=_meta("diff"))
