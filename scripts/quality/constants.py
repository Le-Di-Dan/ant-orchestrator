"""Shared constants for the local quality tooling (single source of truth)."""

from __future__ import annotations

# COD-004: no Python file may exceed this many physical lines.
FILE_LINE_LIMIT = 350

# Directories (relative to the repository root) scanned by the file-size checker.
SCAN_DIRS = ("src", "scripts", "tests")

# Directory names excluded anywhere in a path (caches, venvs, build artifacts).
EXCLUDE_DIRS = frozenset(
    {
        ".git",
        "__pycache__",
        ".venv",
        "venv",
        "build",
        "dist",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
    }
)

# Generated metadata directories are excluded by suffix.
EGG_INFO_SUFFIX = ".egg-info"

# Glob used to select files to check.
FILE_GLOB = "*.py"
