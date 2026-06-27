"""Durable composition receipt — provider-phase recovery bridge (PHASE_5_PLAN CP5 / §4-5).

The receipt makes the provider phase recoverable WITHOUT re-calling the provider once a
draft is durably ``COMPLETED``. It is persisted ``RESERVED`` before invocation,
``INVOKING`` immediately before the external call, ``COMPLETED`` only after a typed draft
is persisted + digest-verified, and ``ENERGY_SETTLED`` after settlement. ``FAILED`` and
``IN_DOUBT`` are controlled terminal states. The linear status is monotonic; the schema
version and checksum are verified on load. It never stores a raw prompt, provider
response, or exception — only typed identity, digests, and artifact references.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Final

from ant_orchestrator.config.constants import (
    COMPOSITION_RECEIPT_SCHEMA_VERSION,
    MAX_ARTIFACT_BYTES,
)
from ant_orchestrator.workers.documentation.errors import (
    CompositionIdentityConflict,
    CompositionReceiptCorrupt,
    InvalidReceiptTransition,
    UnsupportedReceiptVersion,
)

_CHECKSUM_KEY: Final = "checksum"


class CompositionStatus(Enum):
    """Composition-receipt lifecycle (linear states are monotonic)."""

    RESERVED = "reserved"
    INVOKING = "invoking"
    COMPLETED = "completed"
    ENERGY_SETTLED = "energy_settled"
    FAILED = "failed"
    IN_DOUBT = "in_doubt"


_LINEAR: Final[dict[CompositionStatus, int]] = {
    CompositionStatus.RESERVED: 0,
    CompositionStatus.INVOKING: 1,
    CompositionStatus.COMPLETED: 2,
    CompositionStatus.ENERGY_SETTLED: 3,
}
_TERMINAL: Final = frozenset({CompositionStatus.FAILED, CompositionStatus.IN_DOUBT})


@dataclass(frozen=True, slots=True)
class CompositionReceipt:
    """Typed provider-phase record (see module docstring for the durability role)."""

    schema_version: int
    run_id: str
    attempt_id: str
    logical_action_id: str
    proposal_digest: str
    approval_ref: str
    context_manifest_digest: str
    canonical_target: str
    protected_policy_version: int
    invocation_id: str
    energy_reservation_ref: str
    prompt_template_id: str
    prompt_template_version: int
    status: str
    revision: int
    adapter_provider: str | None = None
    model_id: str | None = None
    draft_ref: str | None = None
    draft_digest: str | None = None
    proposed_digest: str | None = None
    usage_status: str | None = None
    usage_tokens_total: int | None = None
    energy_settlement_ref: str | None = None
    settlement_actual_tokens: int | None = None
    settlement_fallback_used: bool = False
    over_budget: bool = False
    failure_code: str | None = None

    @property
    def status_enum(self) -> CompositionStatus:
        return CompositionStatus(self.status)

    def identity(self) -> tuple[str, str, str, str]:
        """Stable identity chain: run / logical action / proposal / attempt."""
        return (self.run_id, self.logical_action_id, self.proposal_digest, self.attempt_id)

    def ensure_same_draft(self, draft_digest: str) -> None:
        """Fail closed if this receipt already bound a different draft digest."""
        if self.draft_digest is not None and self.draft_digest != draft_digest:
            raise CompositionIdentityConflict("composition identity bound a different draft digest")

    def advance_to(self, new_status: CompositionStatus) -> CompositionReceipt:
        """Advance one monotonic linear step (idempotent if unchanged)."""
        current = self.status_enum
        if new_status is current:
            return self
        if current in _TERMINAL or new_status not in _LINEAR or current not in _LINEAR:
            raise InvalidReceiptTransition(f"{current.value} -> {new_status.value} not allowed")
        if _LINEAR[new_status] != _LINEAR[current] + 1:
            raise InvalidReceiptTransition(f"{current.value} -> {new_status.value} not allowed")
        return replace(self, status=new_status.value, revision=self.revision + 1)

    def complete(
        self,
        *,
        provider: str | None,
        model: str | None,
        draft_ref: str,
        draft_digest: str,
        proposed_digest: str,
        usage_status: str,
        usage_tokens_total: int | None,
    ) -> CompositionReceipt:
        """Advance to COMPLETED and bind the durable draft + sanitized usage facts."""
        advanced = self.advance_to(CompositionStatus.COMPLETED)
        return replace(
            advanced,
            adapter_provider=provider,
            model_id=model,
            draft_ref=draft_ref,
            draft_digest=draft_digest,
            proposed_digest=proposed_digest,
            usage_status=usage_status,
            usage_tokens_total=usage_tokens_total,
        )

    def settled(
        self,
        *,
        settlement_ref: str,
        actual_tokens: int,
        fallback_used: bool,
        over_budget: bool,
    ) -> CompositionReceipt:
        """Advance to ENERGY_SETTLED and bind the durable settlement facts."""
        advanced = self.advance_to(CompositionStatus.ENERGY_SETTLED)
        return replace(
            advanced,
            energy_settlement_ref=settlement_ref,
            settlement_actual_tokens=actual_tokens,
            settlement_fallback_used=fallback_used,
            over_budget=over_budget,
        )

    def to_terminal(self, status: CompositionStatus, failure_code: str) -> CompositionReceipt:
        """Move to a controlled terminal state (FAILED / IN_DOUBT) from any non-terminal."""
        if status not in _TERMINAL:
            raise InvalidReceiptTransition(f"{status.value} is not a terminal state")
        if self.status_enum in _TERMINAL:
            return self
        return replace(
            self, status=status.value, failure_code=failure_code, revision=self.revision + 1
        )

    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "logical_action_id": self.logical_action_id,
            "proposal_digest": self.proposal_digest,
            "approval_ref": self.approval_ref,
            "context_manifest_digest": self.context_manifest_digest,
            "canonical_target": self.canonical_target,
            "protected_policy_version": self.protected_policy_version,
            "invocation_id": self.invocation_id,
            "energy_reservation_ref": self.energy_reservation_ref,
            "prompt_template_id": self.prompt_template_id,
            "prompt_template_version": self.prompt_template_version,
            "status": self.status,
            "revision": self.revision,
            "adapter_provider": self.adapter_provider,
            "model_id": self.model_id,
            "draft_ref": self.draft_ref,
            "draft_digest": self.draft_digest,
            "proposed_digest": self.proposed_digest,
            "usage_status": self.usage_status,
            "usage_tokens_total": self.usage_tokens_total,
            "energy_settlement_ref": self.energy_settlement_ref,
            "settlement_actual_tokens": self.settlement_actual_tokens,
            "settlement_fallback_used": self.settlement_fallback_used,
            "over_budget": self.over_budget,
            "failure_code": self.failure_code,
        }

    def checksum(self) -> str:
        canonical = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_json(self) -> str:
        document = self._payload()
        document[_CHECKSUM_KEY] = self.checksum()
        return json.dumps(document, ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_document(cls, document: dict[str, object]) -> CompositionReceipt:
        version = document.get("schema_version")
        if version != COMPOSITION_RECEIPT_SCHEMA_VERSION:
            raise UnsupportedReceiptVersion(f"unsupported receipt schema version: {version}")
        stored = document.get(_CHECKSUM_KEY)
        payload = {k: v for k, v in document.items() if k != _CHECKSUM_KEY}
        try:
            receipt = cls(**payload)  # type: ignore[arg-type]
        except TypeError:
            raise CompositionReceiptCorrupt("receipt document has unexpected fields") from None
        if not isinstance(stored, str) or receipt.checksum() != stored:
            raise CompositionReceiptCorrupt("receipt checksum mismatch")
        return receipt


class CompositionReceiptStore:
    """Persists/loads the composition receipt for one attempt (one file, atomic)."""

    def __init__(self, receipt_path: Path) -> None:
        self._path = receipt_path

    def exists(self) -> bool:
        return self._path.exists()

    def save(self, receipt: CompositionReceipt) -> None:
        if self._path.is_symlink():
            raise CompositionReceiptCorrupt("refusing to write receipt through a symlink")
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.parent / (self._path.name + ".tmp")
        data = receipt.to_json().encode("utf-8")
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, self._path)
        self._fsync_dir()

    def load(self) -> CompositionReceipt:
        if self._path.is_symlink():
            raise CompositionReceiptCorrupt("refusing to read receipt through a symlink")
        try:
            raw = self._path.read_bytes()
        except OSError:
            raise CompositionReceiptCorrupt("receipt is missing") from None
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise CompositionReceiptCorrupt("receipt exceeds the size limit")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise CompositionReceiptCorrupt("receipt is not valid JSON") from None
        if not isinstance(document, dict):
            raise CompositionReceiptCorrupt("receipt is not an object")
        return CompositionReceipt.from_document(document)

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
