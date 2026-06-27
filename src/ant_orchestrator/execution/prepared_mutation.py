"""Prepared-mutation journal — durable, versioned, checksummed bridge (PHASE_5_PLAN CP4).

The journal is the recovery bridge between the two durability domains (filesystem
artifacts and, later, SQLite records). It is persisted ``PREPARED`` BEFORE the target is
touched, advanced to ``PUBLISHED`` after an atomic publish + digest verification, and
exposes a ``COMPLETED`` transition for CP6 after DB reconciliation. Status is monotonic;
the checksum and schema version are verified on load. It never stores a raw prompt,
provider response, or exception — only typed identity, digests, and artifact references.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Final

from ant_orchestrator.config.constants import JOURNAL_SCHEMA_VERSION, MAX_ARTIFACT_BYTES
from ant_orchestrator.core.domain.errors import DomainError

_CHECKSUM_KEY: Final = "checksum"


class JournalError(DomainError):
    """Base class for journal integrity / lifecycle failures (fail-closed)."""


class JournalCorrupt(JournalError):
    """The journal is missing, malformed, or fails its checksum."""


class UnsupportedJournalVersion(JournalError):
    """The journal schema version is not supported by this code."""


class InvalidJournalTransition(JournalError):
    """A status transition is backward or skips a required state."""


class JournalConflict(JournalError):
    """An existing journal shares this identity but carries a different digest."""


class JournalStatus(Enum):
    """Monotonic prepared-mutation lifecycle."""

    PREPARED = "prepared"
    PUBLISHED = "published"
    COMPLETED = "completed"


_ORDER: Final[dict[JournalStatus, int]] = {
    JournalStatus.PREPARED: 0,
    JournalStatus.PUBLISHED: 1,
    JournalStatus.COMPLETED: 2,
}


@dataclass(frozen=True, slots=True)
class MutationJournal:
    """Typed prepared-mutation record (see module docstring for the durability role)."""

    schema_version: int
    run_id: str
    attempt_id: str
    logical_action_id: str
    proposal_digest: str
    approval_ref: str
    context_digest: str
    canonical_target: str
    operation: str
    protected_policy_version: int
    before_kind: str
    previous_digest: str | None
    proposed_digest: str
    before_ref: str
    before_digest: str
    proposed_ref: str
    proposed_digest_ref: str
    diff_ref: str
    diff_digest: str
    validation_ok: bool
    status: str
    revision: int

    @property
    def status_enum(self) -> JournalStatus:
        return JournalStatus(self.status)

    def identity(self) -> tuple[str, str, str, str]:
        """The stable identity chain: run / logical action / proposal / attempt."""
        return (self.run_id, self.logical_action_id, self.proposal_digest, self.attempt_id)

    def advance_to(self, new_status: JournalStatus) -> MutationJournal:
        """Return a journal advanced one monotonic step (idempotent if unchanged)."""
        current = self.status_enum
        if new_status is current:
            return self
        if _ORDER[new_status] != _ORDER[current] + 1:
            raise InvalidJournalTransition(f"{current.value} -> {new_status.value} not allowed")
        return replace(self, status=new_status.value, revision=self.revision + 1)

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "logical_action_id": self.logical_action_id,
            "proposal_digest": self.proposal_digest,
            "approval_ref": self.approval_ref,
            "context_digest": self.context_digest,
            "canonical_target": self.canonical_target,
            "operation": self.operation,
            "protected_policy_version": self.protected_policy_version,
            "before_kind": self.before_kind,
            "previous_digest": self.previous_digest,
            "proposed_digest": self.proposed_digest,
            "before_ref": self.before_ref,
            "before_digest": self.before_digest,
            "proposed_ref": self.proposed_ref,
            "proposed_digest_ref": self.proposed_digest_ref,
            "diff_ref": self.diff_ref,
            "diff_digest": self.diff_digest,
            "validation_ok": self.validation_ok,
            "status": self.status,
            "revision": self.revision,
        }

    def checksum(self) -> str:
        canonical = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        document = self._payload()
        document[_CHECKSUM_KEY] = self.checksum()
        return json.dumps(document, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_document(cls, document: dict[str, object]) -> MutationJournal:
        version = document.get("schema_version")
        if version != JOURNAL_SCHEMA_VERSION:
            raise UnsupportedJournalVersion(f"unsupported journal schema version: {version}")
        stored = document.get(_CHECKSUM_KEY)
        payload = {k: v for k, v in document.items() if k != _CHECKSUM_KEY}
        try:
            journal = cls(**payload)  # type: ignore[arg-type]
        except TypeError:
            raise JournalCorrupt("journal document has unexpected fields") from None
        if not isinstance(stored, str) or journal.checksum() != stored:
            raise JournalCorrupt("journal checksum mismatch")
        return journal


class JournalStore:
    """Persists/loads the prepared-mutation journal for one attempt (one file)."""

    def __init__(self, journal_path: Path) -> None:
        self._path = journal_path

    def exists(self) -> bool:
        return self._path.exists()

    def save(self, journal: MutationJournal) -> None:
        """Atomically persist the journal (flushed), refusing to write a symlink."""
        if self._path.is_symlink():
            raise JournalCorrupt("refusing to write journal through a symlink")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.parent / (self._path.name + ".tmp")
        data = journal.to_json().encode("utf-8")
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._path)
        self._fsync_dir()

    def load(self) -> MutationJournal:
        """Load + verify schema version and checksum; fail closed on any corruption."""
        if self._path.is_symlink():
            raise JournalCorrupt("refusing to read journal through a symlink")
        try:
            raw = self._path.read_bytes()
        except OSError:
            raise JournalCorrupt("journal is missing") from None
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise JournalCorrupt("journal exceeds the size limit")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise JournalCorrupt("journal is not valid JSON") from None
        if not isinstance(document, dict):
            raise JournalCorrupt("journal is not an object")
        return MutationJournal.from_document(document)

    def _fsync_dir(self) -> None:
        try:
            fd = os.open(self._path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        except OSError:
            pass
        finally:
            os.close(fd)
