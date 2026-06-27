"""System-managed mutation artifacts: before/proposed/diff/journal (PHASE_5_PLAN CP4).

Artifacts live under a system-managed root keyed by run/attempt identity, OUTSIDE any
worker document write scope. Paths are encoded from identity (never model-chosen),
writes are atomic + flushed, reads verify a SHA-256 digest, every file is byte-bounded,
and symlinks are rejected on both write and read. A BEFORE state is typed ``ABSENT`` for
CREATE — never an ambiguous empty file.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from ant_orchestrator.config.constants import MAX_ARTIFACT_BYTES
from ant_orchestrator.core.domain.errors import DomainError

_ENC_LEN: Final = 32


class ArtifactError(DomainError):
    """Base class for artifact persistence/integrity failures (fail-closed)."""


class ArtifactCorrupt(ArtifactError):
    """An artifact is missing, undecodable, or fails its digest check."""


class ArtifactTooLarge(ArtifactError):
    """An artifact exceeds the bounded size limit."""


class ArtifactRootViolation(ArtifactError):
    """A reference escapes the artifact root or resolves through a symlink."""


def sha256_text(text: str) -> str:
    """SHA-256 of UTF-8 text — the single digest function for CP4 artifacts."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _encode_segment(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_ENC_LEN]


class BeforeKind(Enum):
    """Whether the target existed before the mutation."""

    ABSENT = "absent"
    PRESENT = "present"


@dataclass(frozen=True, slots=True)
class BeforeState:
    """Typed before-state: ABSENT for CREATE, PRESENT(content+digest) for UPDATE."""

    kind: BeforeKind
    content: str | None
    digest: str | None

    @classmethod
    def absent(cls) -> BeforeState:
        return cls(BeforeKind.ABSENT, None, None)

    @classmethod
    def present(cls, content: str) -> BeforeState:
        return cls(BeforeKind.PRESENT, content, sha256_text(content))


class ArtifactKind(Enum):
    """System artifact kinds persisted per attempt (mutation + CP5 composition phase)."""

    BEFORE = "before"
    PROPOSED = "proposed"
    DIFF = "diff"
    JOURNAL = "journal"
    # CP5 provider-phase artifacts live under a ``composition/`` subdir of the same
    # attempt root so the single atomic writer/reader is reused, never duplicated.
    COMPOSITION_DRAFT = "composition_draft"
    COMPOSITION_RECEIPT = "composition_receipt"


_FILENAMES: Final[dict[ArtifactKind, str]] = {
    ArtifactKind.BEFORE: "before.json",
    ArtifactKind.PROPOSED: "proposed.txt",
    ArtifactKind.DIFF: "diff.patch",
    ArtifactKind.JOURNAL: "journal.json",
    ArtifactKind.COMPOSITION_DRAFT: "composition/draft.json",
    ArtifactKind.COMPOSITION_RECEIPT: "composition/receipt.json",
}


@dataclass(frozen=True, slots=True)
class ArtifactRoot:
    """Per-attempt artifact directory derived from run/attempt identity."""

    artifacts_root: Path
    run_id: str
    attempt_id: str

    def _segment(self) -> str:
        return f"{_encode_segment(self.run_id)}/{_encode_segment(self.attempt_id)}"

    def attempt_dir(self) -> Path:
        return self.artifacts_root / _encode_segment(self.run_id) / _encode_segment(self.attempt_id)

    def path_for(self, kind: ArtifactKind) -> Path:
        return self.attempt_dir() / _FILENAMES[kind]

    def ref_for(self, kind: ArtifactKind) -> str:
        """Reference relative to the artifact root (stored in the journal)."""
        return f"{self._segment()}/{_FILENAMES[kind]}"

    def resolve_ref(self, ref: str) -> Path:
        """Resolve a stored ref under the root, rejecting escape/symlink."""
        target = (self.artifacts_root / ref).resolve()
        root = self.artifacts_root.resolve()
        if target != root and root not in target.parents:
            raise ArtifactRootViolation("artifact reference escapes the artifact root")
        return target


def write_artifact(path: Path, content: str) -> str:
    """Atomically write ``content`` (flushed) and return its SHA-256; reject symlink/oversize."""
    data = content.encode("utf-8")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactTooLarge(f"artifact exceeds {MAX_ARTIFACT_BYTES} bytes")
    if path.is_symlink():
        raise ArtifactRootViolation("refusing to write through a symlink")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / (path.name + ".tmp")
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)
    return sha256_text(content)


def read_artifact(path: Path, expected_digest: str) -> str:
    """Read + verify an artifact against ``expected_digest``; fail closed otherwise."""
    if path.is_symlink():
        raise ArtifactRootViolation("refusing to read through a symlink")
    try:
        data = path.read_bytes()
    except OSError:
        raise ArtifactCorrupt("artifact is missing") from None
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactTooLarge("artifact exceeds the size limit")
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        raise ArtifactCorrupt("artifact is not valid UTF-8") from None
    if sha256_text(text) != expected_digest:
        raise ArtifactCorrupt("artifact digest mismatch")
    return text


def fsync_dir(directory: Path) -> None:
    """Best-effort parent-directory flush (silently skipped where unsupported)."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


_fsync_dir = fsync_dir
