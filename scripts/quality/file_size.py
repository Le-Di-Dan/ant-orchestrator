"""File-size policy checker (COD-004).

Scans the configured source directories for ``*.py`` files and reports any whose
physical line count exceeds the limit. Counting only — no AST or literal analysis.

Must be run from the repository root (``python -m scripts.quality.file_size``).
"""

from __future__ import annotations

from pathlib import Path

from scripts.quality.constants import (
    EGG_INFO_SUFFIX,
    EXCLUDE_DIRS,
    FILE_GLOB,
    FILE_LINE_LIMIT,
    SCAN_DIRS,
)


def count_lines(path: Path) -> int:
    """Count physical lines, including a final line without a trailing newline."""
    text = path.read_text(encoding="utf-8")
    return len(text.splitlines())


def _is_excluded(relative: Path, exclude_dirs: frozenset[str]) -> bool:
    """Return True if any path part is an excluded directory or egg-info metadata."""
    for part in relative.parts:
        if part in exclude_dirs or part.endswith(EGG_INFO_SUFFIX):
            return True
    return False


def find_oversized_files(
    root: Path,
    limit: int = FILE_LINE_LIMIT,
    scan_dirs: tuple[str, ...] = SCAN_DIRS,
    exclude_dirs: frozenset[str] = EXCLUDE_DIRS,
) -> list[tuple[Path, int]]:
    """Return ``(relative_path, line_count)`` for files over ``limit``, sorted by path."""
    violations: list[tuple[Path, int]] = []
    for scan_dir in scan_dirs:
        base = root / scan_dir
        if not base.is_dir():
            continue
        for path in base.rglob(FILE_GLOB):
            if not path.is_file():
                continue
            relative = path.relative_to(root)
            if _is_excluded(relative, exclude_dirs):
                continue
            line_count = count_lines(path)
            if line_count > limit:
                violations.append((relative, line_count))
    violations.sort(key=lambda item: item[0].as_posix())
    return violations


def format_violation(relative: Path, line_count: int, limit: int = FILE_LINE_LIMIT) -> str:
    """Render a single violation: ``path: N lines (limit L)`` with a POSIX path."""
    return f"{relative.as_posix()}: {line_count} lines (limit {limit})"


def main() -> int:
    """Print any violations found under the current working directory; return exit code."""
    root = Path.cwd()
    violations = find_oversized_files(root)
    if not violations:
        print(f"file-size: OK (no Python file exceeds {FILE_LINE_LIMIT} lines)")
        return 0
    print(f"file-size: {len(violations)} file(s) exceed {FILE_LINE_LIMIT} lines:")
    for relative, line_count in violations:
        print(f"  {format_violation(relative, line_count)}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
