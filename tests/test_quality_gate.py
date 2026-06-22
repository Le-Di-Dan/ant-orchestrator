"""Tests for the unified quality gate runner (scripts.quality.gate)."""

from collections.abc import Sequence

from scripts.quality.gate import GATES, run_gates


def test_gate_names_and_order() -> None:
    assert [name for name, _ in GATES] == [
        "ruff-lint",
        "ruff-format",
        "mypy",
        "file-size",
        "pytest",
    ]


def test_command_arrays_are_correct() -> None:
    commands = dict(GATES)
    assert commands["ruff-lint"][1:] == ["-m", "ruff", "check", "."]
    assert commands["ruff-format"][1:] == ["-m", "ruff", "format", "--check", "."]
    assert commands["mypy"][1:] == ["-m", "mypy", "src", "scripts"]
    assert commands["file-size"][1:] == ["-m", "scripts.quality.file_size"]
    assert commands["pytest"][1:] == ["-m", "pytest"]


def test_ruff_format_uses_check_flag() -> None:
    commands = dict(GATES)
    assert "--check" in commands["ruff-format"]


def test_all_pass_returns_zero() -> None:
    calls: list[Sequence[str]] = []

    def runner(argv: Sequence[str]) -> int:
        calls.append(argv)
        return 0

    assert run_gates(GATES, runner) == 0
    assert len(calls) == len(GATES)


def test_single_failure_makes_total_fail() -> None:
    def runner(argv: Sequence[str]) -> int:
        return 1 if "mypy" in argv else 0

    assert run_gates(GATES, runner) == 1


def test_multiple_failures_still_run_all_gates() -> None:
    calls: list[Sequence[str]] = []

    def runner(argv: Sequence[str]) -> int:
        calls.append(argv)
        return 1 if ("mypy" in argv or "pytest" in argv) else 0

    assert run_gates(GATES, runner) == 1
    assert len(calls) == len(GATES)


def test_oserror_is_reported_as_failure() -> None:
    def runner(argv: Sequence[str]) -> int:
        raise OSError("cannot start")

    assert run_gates(GATES, runner) == 1
