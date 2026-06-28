"""CP3 — pure pytest summary parser + exit-code semantics (no Docker, §6/§8)."""

from __future__ import annotations

from ant_orchestrator.workers.test.pytest_outcome import (
    is_interrupted_exit,
    parse_counts,
    result_for_exit_code,
)
from ant_orchestrator.workers.test.report import TestResult


def test_exit_code_maps_to_result() -> None:
    assert result_for_exit_code(0) is TestResult.PASSED
    assert result_for_exit_code(1) is TestResult.FAILED
    assert result_for_exit_code(2) is TestResult.ERROR
    assert result_for_exit_code(3) is TestResult.ERROR
    assert result_for_exit_code(4) is TestResult.ERROR
    assert result_for_exit_code(5) is TestResult.NO_TESTS
    assert result_for_exit_code(None) is TestResult.ERROR
    assert is_interrupted_exit(2) is True
    assert is_interrupted_exit(1) is False


def test_all_pass_summary() -> None:
    counts = parse_counts("==== 12 passed in 0.34s ====")
    assert counts.available and counts.passed == 12 and counts.failed == 0


def test_failed_summary() -> None:
    counts = parse_counts("==== 2 failed, 10 passed in 1.20s ====")
    assert counts.available and counts.failed == 2 and counts.passed == 10


def test_errors_and_skipped_xfail_xpass() -> None:
    line = "= 1 failed, 3 passed, 2 skipped, 1 xfailed, 1 xpassed, 1 error in 0.5s ="
    counts = parse_counts(line)
    assert counts.failed == 1
    assert counts.passed == 3
    assert counts.skipped == 2
    assert counts.xfailed == 1
    assert counts.xpassed == 1
    assert counts.errors == 1


def test_uses_last_summary_line_only() -> None:
    text = "1 passed earlier note\nfoo\n==== 5 passed in 0.1s ===="
    counts = parse_counts(text)
    assert counts.passed == 5


def test_strips_ansi_sequences() -> None:
    counts = parse_counts("\x1b[32m==== 7 passed in 0.1s ====\x1b[0m")
    assert counts.available and counts.passed == 7


def test_no_summary_returns_unavailable() -> None:
    assert parse_counts("collecting ... truncated output").available is False
    assert parse_counts("").available is False


def test_malformed_output_unavailable() -> None:
    assert parse_counts("passed failed error").available is False
