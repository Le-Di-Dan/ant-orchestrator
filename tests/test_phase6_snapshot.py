"""CP2 — exact-byte execution snapshot integrity and scope enforcement (no Docker)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ant_orchestrator.execution.test_snapshot import (
    ExecutionSnapshotBuilder,
    SnapshotScopeViolation,
    SnapshotTooLarge,
    SnapshotUnsafeEntry,
    cleanup_snapshot,
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(tmp_path: Path) -> Path:
    root = tmp_path / "canonical"
    (root / "src").mkdir(parents=True)
    (root / "tests").mkdir()
    (root / ".git").mkdir()
    (root / "src" / "mod.py").write_text("print('hello')\n", encoding="utf-8")
    (root / "tests" / "test_mod.py").write_text(
        "def test_x():\n    assert True\n", encoding="utf-8"
    )
    (root / "src" / "data.bin").write_bytes(bytes(range(256)))
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "secret.env").write_text("API_KEY=should-not-be-copied\n", encoding="utf-8")
    return root


def _staging(tmp_path: Path, name: str = "snap1") -> Path:
    return tmp_path / "snapshots" / name


def test_exact_bytes_preserved_including_binary(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root)
    snap = builder.build(("src", "tests"), _staging(tmp_path))
    staged_bin = snap.staging_root / "src" / "data.bin"
    assert staged_bin.read_bytes() == bytes(range(256))
    assert _digest(staged_bin) == _digest(root / "src" / "data.bin")


def test_manifest_digest_matches_canonical_and_is_deterministic(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root)
    snap_a = builder.build(("src", "tests"), _staging(tmp_path, "a"))
    snap_b = builder.build(("src", "tests"), _staging(tmp_path, "b"))
    assert snap_a.manifest.aggregate_digest == snap_b.manifest.aggregate_digest
    by_rel = {e.rel_path: e.digest for e in snap_a.manifest.entries}
    assert by_rel["src/mod.py"] == _digest(root / "src" / "mod.py")
    assert builder.verify(snap_a)


def test_git_and_out_of_scope_secret_are_not_copied(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root)
    snap = builder.build(("src", "tests"), _staging(tmp_path))
    rels = {e.rel_path for e in snap.manifest.entries}
    assert not any(r.startswith(".git") for r in rels)
    assert "secret.env" not in rels  # outside approved scope -> never materialized
    assert not (snap.staging_root / "secret.env").exists()


def test_git_scope_entry_is_rejected(tmp_path: Path) -> None:
    builder = ExecutionSnapshotBuilder(_canonical(tmp_path))
    with pytest.raises(SnapshotScopeViolation):
        builder.build((".git",), _staging(tmp_path))


@pytest.mark.parametrize("bad", ["/abs/path", "../escape", "a:b", "sub/../x"])
def test_absolute_and_traversal_scope_entries_rejected(tmp_path: Path, bad: str) -> None:
    builder = ExecutionSnapshotBuilder(_canonical(tmp_path))
    with pytest.raises(SnapshotScopeViolation):
        builder.build((bad,), _staging(tmp_path))


def test_duplicate_scope_entry_is_a_collision(tmp_path: Path) -> None:
    builder = ExecutionSnapshotBuilder(_canonical(tmp_path))
    with pytest.raises(SnapshotUnsafeEntry):
        builder.build(("src", "src"), _staging(tmp_path))


def test_file_count_budget_enforced(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root, max_files=1)
    with pytest.raises(SnapshotTooLarge):
        builder.build(("src", "tests"), _staging(tmp_path))


def test_total_byte_budget_enforced(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root, max_total_bytes=8)
    with pytest.raises(SnapshotTooLarge):
        builder.build(("src",), _staging(tmp_path))


def test_per_file_byte_budget_enforced(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root, max_file_bytes=4)
    with pytest.raises(SnapshotTooLarge):
        builder.build(("src",), _staging(tmp_path))


def test_verify_detects_tampering(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    builder = ExecutionSnapshotBuilder(root)
    snap = builder.build(("src",), _staging(tmp_path))
    (snap.staging_root / "src" / "mod.py").write_text("tampered\n", encoding="utf-8")
    assert not builder.verify(snap)


def test_cleanup_only_under_owned_root_and_idempotent(tmp_path: Path) -> None:
    owned = tmp_path / "snapshots"
    staging = _staging(tmp_path)
    ExecutionSnapshotBuilder(_canonical(tmp_path)).build(("src",), staging)
    cleanup_snapshot(staging, owned)
    assert not staging.exists()
    cleanup_snapshot(staging, owned)  # idempotent
    with pytest.raises(SnapshotScopeViolation):
        cleanup_snapshot(tmp_path / "canonical", owned)


def test_symlink_scope_entry_rejected_when_supported(tmp_path: Path) -> None:
    root = _canonical(tmp_path)
    link = root / "link_dir"
    try:
        link.symlink_to(root / "src", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("host cannot create symlinks (Windows without privilege)")
    builder = ExecutionSnapshotBuilder(root)
    with pytest.raises(SnapshotUnsafeEntry):
        builder.build(("link_dir",), _staging(tmp_path))
