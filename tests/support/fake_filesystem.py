"""In-memory FakeFileSystemAdapter test double (CP5). Touches no real filesystem."""

from __future__ import annotations

from collections.abc import Mapping

from ant_orchestrator.application.ports.filesystem import (
    FileReadRequest,
    FileReadResult,
    FileWriteRequest,
    FileWriteResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError, ToolNotFoundError


def _meta(operation: str) -> ToolInvocationMetadata:
    return ToolInvocationMetadata(tool=ToolKind.FILESYSTEM, operation=operation)


class FakeFileSystemAdapter:
    """A scriptable in-memory filesystem; never reads or writes real files."""

    def __init__(
        self,
        *,
        files: Mapping[str, str] | None = None,
        error: ToolAdapterError | None = None,
    ) -> None:
        self._files: dict[str, str] = dict(files) if files is not None else {}
        self._error = error
        self.reads: list[FileReadRequest] = []
        self.writes: list[FileWriteRequest] = []

    async def read_text(self, request: FileReadRequest) -> FileReadResult:
        self.reads.append(request)
        if self._error is not None:
            raise self._error
        if request.path not in self._files:
            raise ToolNotFoundError(tool="filesystem", operation="read_text")
        return FileReadResult(
            path=request.path, content=self._files[request.path], invocation=_meta("read_text")
        )

    async def write_text(self, request: FileWriteRequest) -> FileWriteResult:
        self.writes.append(request)
        if self._error is not None:
            raise self._error
        changed = self._files.get(request.path) != request.content
        self._files[request.path] = request.content
        return FileWriteResult(path=request.path, changed=changed, invocation=_meta("write_text"))
