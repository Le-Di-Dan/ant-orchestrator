"""Unified local quality gate runner.

Runs every gate sequentially via subprocess, aggregates the results, and returns a
non-zero exit code if any gate fails. Gates always run to completion (no
short-circuit) so every failure is surfaced. Must be run from the repository root
(``python -m scripts.quality.gate``).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence

# Ordered gates: (name, command-array). Commands use the running interpreter and
# module invocation (``-m``) so the gate is cross-platform and needs no shell.
GATES: list[tuple[str, list[str]]] = [
    ("ruff-lint", [sys.executable, "-m", "ruff", "check", "."]),
    ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("mypy", [sys.executable, "-m", "mypy", "src", "scripts"]),
    ("file-size", [sys.executable, "-m", "scripts.quality.file_size"]),
    ("pytest", [sys.executable, "-m", "pytest"]),
]

Runner = Callable[[Sequence[str]], int]


def _default_runner(argv: Sequence[str]) -> int:
    """Run a command and return its process exit code."""
    return subprocess.run(list(argv), check=False).returncode


def run_gates(
    gates: Sequence[tuple[str, list[str]]],
    runner: Runner = _default_runner,
) -> int:
    """Run all gates without short-circuit, print a summary, return 0 iff all pass."""
    results: list[tuple[str, int]] = []
    for name, argv in gates:
        print(f"== gate: {name} ==")
        try:
            code = runner(argv)
        except OSError as exc:
            print(f"  gate '{name}' failed to start: {exc}")
            code = 1
        results.append((name, code))
    print("== summary ==")
    failed = 0
    for name, code in results:
        status = "PASS" if code == 0 else "FAIL"
        print(f"  {name}: {status} (exit {code})")
        if code != 0:
            failed += 1
    return 0 if failed == 0 else 1


def main() -> int:
    """Entry point for ``python -m scripts.quality.gate``."""
    return run_gates(GATES)


if __name__ == "__main__":
    raise SystemExit(main())
