"""FakeFileSystemAdapter contract conformance + fake-specific tests (CP5)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import FrozenInstanceError

import pytest

from ant_orchestrator.application.ports.filesystem import (
    FileReadRequest,
    FileSystemAdapter,
    FileWriteRequest,
)
from ant_orchestrator.application.ports.tool_errors import ToolPermissionError, ToolTimeoutError
from ant_orchestrator.core.domain.errors import InvariantViolation
from tests.contracts.filesystem_contract import FileSystemContract
from tests.support.fake_filesystem import FakeFileSystemAdapter


class TestFakeFileSystemContract(FileSystemContract):
    def build_adapter(self, files: Mapping[str, str]) -> FileSystemAdapter:
        return FakeFileSystemAdapter(files=files)


def test_fake_records_requests() -> None:
    adapter = FakeFileSystemAdapter(files={"a.txt": "x"})
    read = FileReadRequest("a.txt")
    write = FileWriteRequest("b.txt", "y")
    asyncio.run(adapter.read_text(read))
    asyncio.run(adapter.write_text(write))
    assert adapter.reads == [read]
    assert adapter.writes == [write]


def test_fake_simulates_permission_error() -> None:
    adapter = FakeFileSystemAdapter(error=ToolPermissionError(tool="filesystem"))
    with pytest.raises(ToolPermissionError):
        asyncio.run(adapter.read_text(FileReadRequest("a.txt")))


def test_fake_simulates_timeout_error() -> None:
    adapter = FakeFileSystemAdapter(error=ToolTimeoutError(tool="filesystem"))
    with pytest.raises(ToolTimeoutError) as info:
        asyncio.run(adapter.write_text(FileWriteRequest("a.txt", "x")))
    assert info.value.retryable is True


def test_request_dtos_are_immutable() -> None:
    request = FileReadRequest("a.txt")
    with pytest.raises(FrozenInstanceError):
        request.path = "b.txt"  # type: ignore[misc]


def test_request_rejects_empty_path() -> None:
    with pytest.raises(InvariantViolation):
        FileReadRequest("")
    with pytest.raises(InvariantViolation):
        FileWriteRequest("", "data")
