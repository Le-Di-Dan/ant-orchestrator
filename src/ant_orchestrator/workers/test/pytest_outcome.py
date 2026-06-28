"""Pure pytest acceptance-profile semantics (PHASE_6_PLAN CP3, §6/§8).

pytest exit codes and the summary line are pytest-specific, so this knowledge lives with
the acceptance *profile* — never baked into the generic isolation port. Two pure helpers:

* :func:`result_for_exit_code` maps a COMPLETED run's exit code to a :class:`TestResult`
  using documented pytest exit semantics (0 ok, 1 tests failed, 2 interrupted, 3 internal
  error, 4 usage error, 5 no tests collected). The result stands on exit facts alone.
* :func:`parse_counts` extracts per-bucket counts from *already bounded/redacted* output.
  It is non-brittle: if it cannot find a recognizable summary it returns
  ``TestCounts.unavailable()`` (never fabricated numbers, never changes the result).
"""

from __future__ import annotations

import re

from ant_orchestrator.config.constants import (
    PYTEST_EXIT_INTERRUPTED,
    PYTEST_EXIT_NO_TESTS_COLLECTED,
    PYTEST_EXIT_OK,
    PYTEST_EXIT_TESTS_FAILED,
)
from ant_orchestrator.workers.test.report import TestCounts, TestResult

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_TOKEN = re.compile(r"(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed)\b")
_BUCKET = {
    "passed": "passed",
    "failed": "failed",
    "error": "errors",
    "errors": "errors",
    "skipped": "skipped",
    "xfailed": "xfailed",
    "xpassed": "xpassed",
}


def result_for_exit_code(exit_code: int | None) -> TestResult:
    """Map a *completed* run's pytest exit code to an acceptance :class:`TestResult`."""
    if exit_code == PYTEST_EXIT_OK:
        return TestResult.PASSED
    if exit_code == PYTEST_EXIT_TESTS_FAILED:
        return TestResult.FAILED
    if exit_code == PYTEST_EXIT_NO_TESTS_COLLECTED:
        return TestResult.NO_TESTS
    return TestResult.ERROR  # 2 interrupted, 3 internal, 4 usage, None/other -> error


def is_interrupted_exit(exit_code: int | None) -> bool:
    """True when a completed run reported the pytest 'interrupted' exit code (2)."""
    return exit_code == PYTEST_EXIT_INTERRUPTED


def parse_counts(text: str) -> TestCounts:
    """Parse per-bucket counts from bounded output; ``unavailable`` if not recognizable."""
    if not text:
        return TestCounts.unavailable()
    summary_line = _summary_line(text)
    if summary_line is None:
        return TestCounts.unavailable()
    buckets = {value: 0 for value in set(_BUCKET.values())}
    for raw_count, word in _TOKEN.findall(summary_line):
        buckets[_BUCKET[word]] += int(raw_count)
    return TestCounts(
        available=True,
        passed=buckets["passed"],
        failed=buckets["failed"],
        errors=buckets["errors"],
        skipped=buckets["skipped"],
        xfailed=buckets["xfailed"],
        xpassed=buckets["xpassed"],
    )


def _summary_line(text: str) -> str | None:
    """Return the last line carrying a recognizable count token (the pytest summary)."""
    last: str | None = None
    for raw in text.splitlines():
        line = _ANSI.sub("", raw)
        if _TOKEN.search(line):
            last = line
    return last
