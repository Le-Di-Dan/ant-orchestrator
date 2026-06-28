"""Exact-byte execution snapshot for read-only test isolation (PHASE_6_PLAN CP2, §3.2).

Materializes ONLY the approved read scope into an execution-owned staging directory,
preserving exact bytes (no redaction of source/test/config — the Test Ant must test the
real implementation). Every file gets a relative path, size and SHA-256; the manifest has
a deterministic aggregate digest; each copied byte is verified equal to its canonical
source. Symlinks/reparse points/special files and ``.git`` are rejected fail-closed.

No subprocess, no network. Cleanup only ever deletes under the execution-owned root.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ant_orchestrator.config.constants import (
    MAX_SNAPSHOT_FILE_BYTES,
    MAX_SNAPSHOT_FILES,
    MAX_SNAPSHOT_TOTAL_BYTES,
)
from ant_orchestrator.core.domain.errors import DomainError
from ant_orchestrator.security.windows_path import is_lexically_unsafe, normalize_separators

_GIT_DIR: Final = ".git"
_REPARSE: Final = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class SnapshotError(DomainError):
    """Base class for snapshot build/integrity failures (fail-closed)."""

    __test__ = False  # domain term; not a pytest test class


class SnapshotScopeViolation(SnapshotError):
    """A path escapes the approved canonical scope or the owned staging root."""


class SnapshotIntegrityError(SnapshotError):
    """A copied byte digest does not match its canonical source."""


class SnapshotTooLarge(SnapshotError):
    """The snapshot exceeds a file-count or byte budget."""


class SnapshotUnsafeEntry(SnapshotError):
    """A symlink/reparse point/special file or a path collision was encountered."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_symlink_or_reparse(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    return bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def _is_regular_file(path: Path) -> bool:
    try:
        st = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(st.st_mode)


@dataclass(frozen=True, slots=True)
class SnapshotFileEntry:
    """One materialized file: workspace-relative path, byte size and SHA-256."""

    __test__ = False  # domain term; not a pytest test class

    rel_path: str
    size_bytes: int
    digest: str

    def to_state_dict(self) -> dict[str, object]:
        return {"rel_path": self.rel_path, "size_bytes": self.size_bytes, "digest": self.digest}


@dataclass(frozen=True, slots=True)
class SnapshotManifest:
    """Deterministic manifest of all materialized files with an aggregate digest."""

    __test__ = False  # domain term; not a pytest test class

    entries: tuple[SnapshotFileEntry, ...]
    total_bytes: int
    aggregate_digest: str

    @property
    def file_count(self) -> int:
        return len(self.entries)

    def to_state_dict(self) -> dict[str, object]:
        return {
            "file_count": self.file_count,
            "total_bytes": self.total_bytes,
            "aggregate_digest": self.aggregate_digest,
            "entries": [e.to_state_dict() for e in self.entries],
        }


@dataclass(frozen=True, slots=True)
class ExecutionSnapshot:
    """An exact-byte snapshot staged under an execution-owned root."""

    __test__ = False  # domain term; not a pytest test class

    staging_root: Path
    manifest: SnapshotManifest


def _aggregate_digest(entries: tuple[SnapshotFileEntry, ...]) -> str:
    hasher = hashlib.sha256()
    for entry in entries:
        hasher.update(entry.rel_path.encode("utf-8"))
        hasher.update(b"\x00")
        hasher.update(entry.digest.encode("utf-8"))
        hasher.update(b"\n")
    return hasher.hexdigest()


class ExecutionSnapshotBuilder:
    """Materialize the approved read scope into an exact-byte, verified snapshot."""

    __test__ = False  # domain term; not a pytest test class

    def __init__(
        self,
        canonical_root: Path,
        *,
        max_files: int = MAX_SNAPSHOT_FILES,
        max_total_bytes: int = MAX_SNAPSHOT_TOTAL_BYTES,
        max_file_bytes: int = MAX_SNAPSHOT_FILE_BYTES,
    ) -> None:
        self._root = canonical_root.resolve()
        self._max_files = max_files
        self._max_total = max_total_bytes
        self._max_file = max_file_bytes

    def build(self, approved_read_scope: tuple[str, ...], staging_root: Path) -> ExecutionSnapshot:
        """Copy exact bytes for every approved file and return a verified snapshot."""
        sources = self._collect(approved_read_scope)
        entries: list[SnapshotFileEntry] = []
        seen: set[str] = set()
        total = 0
        for rel, src in sources:
            key = rel.lower()
            if key in seen:
                raise SnapshotUnsafeEntry(f"path collision for {rel!r}")
            seen.add(key)
            data = self._read_exact(src)
            total += len(data)
            if total > self._max_total:
                raise SnapshotTooLarge("snapshot exceeds the total byte budget")
            digest = self._materialize(staging_root, rel, src, data)
            entries.append(SnapshotFileEntry(rel, len(data), digest))
        ordered = tuple(sorted(entries, key=lambda e: e.rel_path))
        manifest = SnapshotManifest(ordered, total, _aggregate_digest(ordered))
        return ExecutionSnapshot(staging_root.resolve(), manifest)

    def verify(self, snapshot: ExecutionSnapshot) -> bool:
        """Re-read the staged files and confirm they still match the manifest."""
        for entry in snapshot.manifest.entries:
            staged = snapshot.staging_root / entry.rel_path
            if _is_symlink_or_reparse(staged) or not _is_regular_file(staged):
                return False
            if _sha256_bytes(staged.read_bytes()) != entry.digest:
                return False
        return True

    # ------------------------------------------------------------------

    def _collect(self, approved_read_scope: tuple[str, ...]) -> list[tuple[str, Path]]:
        collected: list[tuple[str, Path]] = []
        for raw in approved_read_scope:
            normalized = normalize_separators(raw)
            if not normalized or normalized.startswith("/") or is_lexically_unsafe(normalized):
                raise SnapshotScopeViolation(f"unsafe scope entry {raw!r}")
            if ".." in normalized.split("/") or _GIT_DIR in normalized.split("/"):
                raise SnapshotScopeViolation(f"rejected scope entry {raw!r}")
            base = self._root / normalized
            self._assert_within_root(base)
            if _is_symlink_or_reparse(base):
                raise SnapshotUnsafeEntry(f"symlink/reparse scope entry {raw!r}")
            if base.is_dir():
                self._walk_dir(base, collected)
            elif _is_regular_file(base):
                collected.append((self._rel(base), base))
            else:
                raise SnapshotUnsafeEntry(f"non-regular scope entry {raw!r}")
            if len(collected) > self._max_files:
                raise SnapshotTooLarge("snapshot exceeds the file-count budget")
        if not collected:
            raise SnapshotScopeViolation("approved read scope produced no files")
        return collected

    def _walk_dir(self, directory: Path, out: list[tuple[str, Path]]) -> None:
        for child in sorted(directory.iterdir()):
            if child.name == _GIT_DIR or _is_symlink_or_reparse(child):
                if child.name == _GIT_DIR:
                    continue
                raise SnapshotUnsafeEntry(f"symlink/reparse entry {child.name!r}")
            self._assert_within_root(child)
            if child.is_dir():
                self._walk_dir(child, out)
            elif _is_regular_file(child):
                out.append((self._rel(child), child))
            else:
                raise SnapshotUnsafeEntry(f"non-regular file {child.name!r}")
            if len(out) > self._max_files:
                raise SnapshotTooLarge("snapshot exceeds the file-count budget")

    def _assert_within_root(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved != self._root and self._root not in resolved.parents:
            raise SnapshotScopeViolation(f"path escapes canonical root: {path.name}")

    def _rel(self, path: Path) -> str:
        return normalize_separators(str(path.resolve().relative_to(self._root)))

    def _read_exact(self, src: Path) -> bytes:
        st = src.lstat()
        if st.st_size > self._max_file:
            raise SnapshotTooLarge(f"file exceeds the per-file budget: {src.name}")
        return src.read_bytes()

    def _materialize(self, staging_root: Path, rel: str, src: Path, data: bytes) -> str:
        dest = staging_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        digest = _sha256_bytes(data)
        if _sha256_bytes(src.read_bytes()) != digest or _sha256_bytes(dest.read_bytes()) != digest:
            raise SnapshotIntegrityError(f"snapshot byte mismatch for {rel!r}")
        return digest


def cleanup_snapshot(staging_root: Path, owned_root: Path) -> None:
    """Idempotently delete a staging tree, only ever under the execution-owned root."""
    staging = staging_root.resolve()
    owned = owned_root.resolve()
    if staging != owned and owned not in staging.parents:
        raise SnapshotScopeViolation("refusing to delete outside the owned artifact root")
    if not staging.exists():
        return
    if _is_symlink_or_reparse(staging):
        raise SnapshotUnsafeEntry("refusing to delete through a symlink")
    shutil.rmtree(staging, ignore_errors=False)
