"""Scriptable FakeTestRunnerAdapter test double (CP5). Runs no real tests."""

from __future__ import annotations

from ant_orchestrator.application.ports.test_runner import (
    TestOutcome,
    TestRunRequest,
    TestRunResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError


def make_test_result(
    *,
    outcome: TestOutcome = TestOutcome.PASSED,
    exit_code: int | None = 0,
    summary: str = "",
    duration_seconds: float = 0.0,
) -> TestRunResult:
    """Build a TestRunResult for scripting fakes/tests."""
    return TestRunResult(
        outcome=outcome,
        duration_seconds=duration_seconds,
        invocation=ToolInvocationMetadata(tool=ToolKind.TEST_RUNNER, operation="run"),
        exit_code=exit_code,
        summary=summary,
    )


class FakeTestRunnerAdapter:
    """Returns scripted results or raises a scripted error; runs no real framework."""

    def __init__(
        self,
        *,
        results: list[TestRunResult] | None = None,
        error: ToolAdapterError | None = None,
    ) -> None:
        self._results = list(results) if results is not None else []
        self._error = error
        self.requests: list[TestRunRequest] = []

    async def run(self, request: TestRunRequest) -> TestRunResult:
        self.requests.append(request)
        if self._error is not None:
            raise self._error
        if self._results:
            return self._results.pop(0)
        return make_test_result()
