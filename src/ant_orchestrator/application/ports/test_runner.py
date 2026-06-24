"""Test-runner tool port: framework-neutral test execution (PHASE_2_PLAN §CP5).

Async and framework-agnostic — no ``pytest``/``jest`` hard-coded and no raw shell
command in the request. A failing test suite is a normal ``FAILED`` result, not an
adapter error; only a runner that cannot launch is an adapter error. No real
execution here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Protocol, runtime_checkable

from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata
from ant_orchestrator.core.domain.errors import InvariantViolation


class TestOutcome(Enum):
    """Neutral test-run outcome (business result, not infrastructure status)."""

    __test__ = False  # domain term; not a pytest test class

    PASSED = "passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TestRunRequest:
    """Run the given (optional) ``targets`` in an optional workspace-relative ``cwd``."""

    __test__ = False  # domain term; not a pytest test class

    targets: tuple[str, ...] = ()
    cwd: str | None = None
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        if self.timeout_seconds is not None and self.timeout_seconds <= 0:
            raise InvariantViolation("TestRunRequest.timeout_seconds must be > 0")


@dataclass(frozen=True, slots=True)
class TestRunResult:
    """A completed test run; ``outcome`` distinguishes pass from fail."""

    __test__ = False  # domain term; not a pytest test class

    outcome: TestOutcome
    duration_seconds: float
    invocation: ToolInvocationMetadata
    exit_code: int | None = None
    summary: str = ""

    def __post_init__(self) -> None:
        if self.duration_seconds < 0:
            raise InvariantViolation("TestRunResult.duration_seconds must be >= 0")


@runtime_checkable
class TestRunnerAdapter(Protocol):
    """Async, framework-neutral test runner."""

    __test__: ClassVar[bool] = False  # domain term; not a pytest test class

    async def run(self, request: TestRunRequest) -> TestRunResult:
        """Run the tests and return PASSED/FAILED; raise only on runner failure."""
        ...
