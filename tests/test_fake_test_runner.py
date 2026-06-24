"""FakeTestRunnerAdapter contract conformance + fake-specific tests (CP5)."""

from __future__ import annotations

import asyncio

import pytest

from ant_orchestrator.application.ports.test_runner import (
    TestOutcome,
    TestRunnerAdapter,
    TestRunRequest,
)
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError, ToolTimeoutError
from ant_orchestrator.core.domain.errors import InvariantViolation
from tests.contracts.test_runner_contract import RunnerContract
from tests.support.fake_test_runner import FakeTestRunnerAdapter, make_test_result


class TestFakeRunnerContract(RunnerContract):
    def build_passing_adapter(self) -> TestRunnerAdapter:
        return FakeTestRunnerAdapter(results=[make_test_result(outcome=TestOutcome.PASSED)])

    def build_failing_adapter(self) -> TestRunnerAdapter:
        return FakeTestRunnerAdapter(
            results=[make_test_result(outcome=TestOutcome.FAILED, exit_code=1)]
        )

    def build_error_adapter(self, error: ToolAdapterError) -> TestRunnerAdapter:
        return FakeTestRunnerAdapter(error=error)


def test_fake_records_requests() -> None:
    adapter = FakeTestRunnerAdapter()
    request = TestRunRequest(targets=("tests/test_x.py",))
    asyncio.run(adapter.run(request))
    assert adapter.requests == [request]


def test_failed_summary_preserved() -> None:
    adapter = FakeTestRunnerAdapter(
        results=[make_test_result(outcome=TestOutcome.FAILED, summary="1 failed")]
    )
    result = asyncio.run(adapter.run(TestRunRequest()))
    assert result.outcome is TestOutcome.FAILED
    assert result.summary == "1 failed"


def test_runner_unavailable_simulation() -> None:
    adapter = FakeTestRunnerAdapter(error=ToolTimeoutError(tool="test_runner"))
    with pytest.raises(ToolTimeoutError) as info:
        asyncio.run(adapter.run(TestRunRequest()))
    assert info.value.retryable is True


def test_negative_timeout_rejected() -> None:
    with pytest.raises(InvariantViolation):
        TestRunRequest(timeout_seconds=-1)
