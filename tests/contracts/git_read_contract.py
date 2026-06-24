"""Reusable GitReadAdapter contract (CP5)."""

from __future__ import annotations

import asyncio
import inspect

import pytest

from ant_orchestrator.application.ports.git_read import (
    GitDiffRequest,
    GitReadAdapter,
    GitStatusRequest,
)
from ant_orchestrator.application.ports.tool_common import ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


class GitReadContract:
    """Shared behavioural contract for any :class:`GitReadAdapter`."""

    def build_clean_adapter(self) -> GitReadAdapter:
        raise NotImplementedError

    def build_dirty_adapter(self) -> GitReadAdapter:
        raise NotImplementedError

    def build_error_adapter(self, error: ToolAdapterError) -> GitReadAdapter:
        raise NotImplementedError

    def test_operations_are_coroutine_functions(self) -> None:
        adapter = self.build_clean_adapter()
        assert inspect.iscoroutinefunction(adapter.status)
        assert inspect.iscoroutinefunction(adapter.diff)

    def test_clean_status_with_evidence(self) -> None:
        result = asyncio.run(self.build_clean_adapter().status(GitStatusRequest()))
        assert result.is_clean is True
        assert result.entries == ()
        assert result.invocation.tool is ToolKind.GIT
        assert result.invocation.operation == "status"

    def test_dirty_status_is_a_result_not_an_error(self) -> None:
        result = asyncio.run(self.build_dirty_adapter().status(GitStatusRequest()))
        assert result.is_clean is False
        assert result.entries

    def test_empty_diff_is_valid(self) -> None:
        result = asyncio.run(self.build_clean_adapter().diff(GitDiffRequest()))
        assert result.diff_text == ""
        assert result.changes == ()

    def test_non_empty_diff_preserved(self) -> None:
        result = asyncio.run(self.build_dirty_adapter().diff(GitDiffRequest()))
        assert result.diff_text
        assert result.changes

    def test_repository_not_found_raises(self) -> None:
        error = ToolAdapterError(tool="git", operation="status")
        with pytest.raises(ToolAdapterError):
            asyncio.run(self.build_error_adapter(error).status(GitStatusRequest()))

    def test_request_not_mutated(self) -> None:
        adapter = self.build_dirty_adapter()
        request = GitDiffRequest(staged=True)
        snapshot = GitDiffRequest(staged=True)
        asyncio.run(adapter.diff(request))
        assert request == snapshot
