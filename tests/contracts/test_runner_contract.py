"""Reusable TestRunnerAdapter contract (CP5).

The base class is named ``RunnerContract`` (no ``Test`` prefix) so pytest does not
collect it directly. A real Phase 3 runner would back the builders with a real,
framework-neutral test invocation.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from ant_orchestrator.application.ports.test_runner import (
    TestOutcome,
    TestRunnerAdapter,
    TestRunRequest,
)
from ant_orchestrator.application.ports.tool_common import ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


class RunnerContract:
    """Shared behavioural contract for any :class:`TestRunnerAdapter`."""

    def build_passing_adapter(self) -> TestRunnerAdapter:
        raise NotImplementedError

    def build_failing_adapter(self) -> TestRunnerAdapter:
        raise NotImplementedError

    def build_error_adapter(self, error: ToolAdapterError) -> TestRunnerAdapter:
        raise NotImplementedError

    def test_run_is_coroutine_function(self) -> None:
        assert inspect.iscoroutinefunction(self.build_passing_adapter().run)

    def test_passed_result_with_evidence(self) -> None:
        result = asyncio.run(self.build_passing_adapter().run(TestRunRequest()))
        assert result.outcome is TestOutcome.PASSED
        assert result.duration_seconds >= 0
        assert result.invocation.tool is ToolKind.TEST_RUNNER
        assert result.invocation.operation == "run"

    def test_failing_suite_is_a_result_not_an_error(self) -> None:
        result = asyncio.run(self.build_failing_adapter().run(TestRunRequest()))
        assert result.outcome is TestOutcome.FAILED

    def test_runner_failure_raises(self) -> None:
        error = ToolAdapterError(tool="test_runner", operation="run")
        adapter = self.build_error_adapter(error)
        with pytest.raises(ToolAdapterError):
            asyncio.run(adapter.run(TestRunRequest()))

    def test_request_not_mutated(self) -> None:
        adapter = self.build_passing_adapter()
        request = TestRunRequest(targets=("a", "b"))
        snapshot = TestRunRequest(targets=("a", "b"))
        asyncio.run(adapter.run(request))
        assert request == snapshot
