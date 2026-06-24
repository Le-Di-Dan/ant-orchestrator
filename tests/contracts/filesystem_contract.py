"""Reusable FileSystemAdapter contract (CP5).

Subclass in a ``Test*`` class and implement ``build_adapter``; the inherited
``test_*`` methods verify the shared public behaviour. Reusable by the real Phase 3
adapter (its ``build_adapter`` would seed a workspace instead of a dict).
"""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping

import pytest

from ant_orchestrator.application.ports.filesystem import (
    FileReadRequest,
    FileSystemAdapter,
    FileWriteRequest,
)
from ant_orchestrator.application.ports.tool_common import ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolNotFoundError


class FileSystemContract:
    """Shared behavioural contract for any :class:`FileSystemAdapter`."""

    def build_adapter(self, files: Mapping[str, str]) -> FileSystemAdapter:
        raise NotImplementedError

    def test_operations_are_coroutine_functions(self) -> None:
        adapter = self.build_adapter({})
        assert inspect.iscoroutinefunction(adapter.read_text)
        assert inspect.iscoroutinefunction(adapter.write_text)

    def test_read_existing_with_evidence(self) -> None:
        adapter = self.build_adapter({"a.txt": "hello"})
        result = asyncio.run(adapter.read_text(FileReadRequest("a.txt")))
        assert result.path == "a.txt"
        assert result.content == "hello"
        assert result.invocation.tool is ToolKind.FILESYSTEM
        assert result.invocation.operation == "read_text"

    def test_read_empty_content_is_valid(self) -> None:
        adapter = self.build_adapter({"e.txt": ""})
        assert asyncio.run(adapter.read_text(FileReadRequest("e.txt"))).content == ""

    def test_missing_read_raises_not_found(self) -> None:
        adapter = self.build_adapter({})
        with pytest.raises(ToolNotFoundError):
            asyncio.run(adapter.read_text(FileReadRequest("missing.txt")))

    def test_write_create_reports_changed(self) -> None:
        adapter = self.build_adapter({})
        result = asyncio.run(adapter.write_text(FileWriteRequest("new.txt", "data")))
        assert result.changed is True
        assert asyncio.run(adapter.read_text(FileReadRequest("new.txt"))).content == "data"

    def test_write_update_change_flag(self) -> None:
        adapter = self.build_adapter({"f.txt": "old"})
        assert asyncio.run(adapter.write_text(FileWriteRequest("f.txt", "new"))).changed is True
        assert asyncio.run(adapter.write_text(FileWriteRequest("f.txt", "new"))).changed is False

    def test_request_not_mutated(self) -> None:
        adapter = self.build_adapter({"a.txt": "x"})
        request = FileReadRequest("a.txt")
        snapshot = FileReadRequest("a.txt")
        asyncio.run(adapter.read_text(request))
        assert request == snapshot
