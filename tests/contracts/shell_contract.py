"""Reusable ShellAdapter contract (CP5).

Subclass and implement the builders. A real Phase 3 adapter would back the builders
with benign commands (``echo`` / ``false``) instead of scripted results.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from ant_orchestrator.application.ports.shell import ShellAdapter, ShellRequest
from ant_orchestrator.application.ports.tool_common import ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


class ShellContract:
    """Shared behavioural contract for any :class:`ShellAdapter`."""

    def build_success_adapter(self) -> ShellAdapter:
        """An adapter whose ``run`` returns exit_code 0."""
        raise NotImplementedError

    def build_nonzero_adapter(self) -> ShellAdapter:
        """An adapter whose ``run`` returns a non-zero exit code (a valid result)."""
        raise NotImplementedError

    def build_error_adapter(self, error: ToolAdapterError) -> ShellAdapter:
        raise NotImplementedError

    def test_run_is_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(self.build_success_adapter().run)

    def test_success_result_structure(self) -> None:
        adapter = self.build_success_adapter()
        result = asyncio.run(adapter.run(ShellRequest(argv=("echo", "hi"))))
        assert result.exit_code == 0
        assert result.duration_seconds >= 0
        assert result.invocation.tool is ToolKind.SHELL
        assert result.invocation.operation == "run"

    def test_nonzero_exit_is_a_result_not_an_error(self) -> None:
        adapter = self.build_nonzero_adapter()
        result = asyncio.run(adapter.run(ShellRequest(argv=("false",))))
        assert result.exit_code != 0

    def test_error_is_propagated_with_sanitized_identity(self) -> None:
        error = ToolAdapterError(tool="shell", operation="run")
        adapter = self.build_error_adapter(error)
        with pytest.raises(ToolAdapterError) as info:
            asyncio.run(adapter.run(ShellRequest(argv=("cmd",))))
        rendered = str(info.value) + repr(info.value)
        assert "shell" in rendered
        assert info.value.code.value in rendered

    def test_request_not_mutated(self) -> None:
        adapter = self.build_success_adapter()
        request = ShellRequest(argv=("echo", "hi"))
        snapshot = ShellRequest(argv=("echo", "hi"))
        asyncio.run(adapter.run(request))
        assert request == snapshot
