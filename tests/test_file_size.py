"""Tests for the file-size policy checker (scripts.quality.file_size)."""

from pathlib import Path

import pytest

from scripts.quality.constants import FILE_LINE_LIMIT
from scripts.quality.file_size import count_lines, find_oversized_files, main


def _write_lines(path: Path, count: int, *, trailing_newline: bool = True) -> None:
    """Create a file with exactly ``count`` physical lines."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"line {i}" for i in range(count))
    if trailing_newline:
        body += "\n"
    path.write_text(body, encoding="utf-8")


def test_file_at_limit_passes(tmp_path: Path) -> None:
    _write_lines(tmp_path / "src" / "ok.py", FILE_LINE_LIMIT)
    assert find_oversized_files(tmp_path) == []


def test_file_over_limit_is_flagged(tmp_path: Path) -> None:
    _write_lines(tmp_path / "src" / "big.py", FILE_LINE_LIMIT + 1)
    result = find_oversized_files(tmp_path)
    assert [p.as_posix() for p, _ in result] == ["src/big.py"]
    assert result[0][1] == FILE_LINE_LIMIT + 1


def test_file_without_trailing_newline_counted(tmp_path: Path) -> None:
    target = tmp_path / "src" / "no_newline.py"
    _write_lines(target, FILE_LINE_LIMIT + 1, trailing_newline=False)
    assert count_lines(target) == FILE_LINE_LIMIT + 1
    assert find_oversized_files(tmp_path)


def test_excluded_directory_ignored(tmp_path: Path) -> None:
    _write_lines(tmp_path / "src" / "__pycache__" / "big.py", FILE_LINE_LIMIT + 1)
    assert find_oversized_files(tmp_path) == []


def test_multiple_violations_sorted(tmp_path: Path) -> None:
    _write_lines(tmp_path / "src" / "b.py", FILE_LINE_LIMIT + 1)
    _write_lines(tmp_path / "scripts" / "a.py", FILE_LINE_LIMIT + 2)
    result = [p.as_posix() for p, _ in find_oversized_files(tmp_path)]
    assert result == ["scripts/a.py", "src/b.py"]


def test_main_returns_zero_when_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_lines(tmp_path / "src" / "ok.py", FILE_LINE_LIMIT)
    assert main() == 0


def test_main_returns_nonzero_on_violation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    _write_lines(tmp_path / "src" / "big.py", FILE_LINE_LIMIT + 1)
    assert main() == 1
