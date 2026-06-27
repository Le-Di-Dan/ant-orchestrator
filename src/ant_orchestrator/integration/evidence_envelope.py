"""Typed, versioned evidence envelope stored in ``evidence.result`` (PHASE_5_PLAN CP6).

CP6 persists Phase-5's rich references (proposal/approval/context/permission/receipt/
energy/journal/artifact digests) WITHOUT a schema migration: they are encoded as a
canonical, bounded, sanitized JSON envelope in the existing ``execution_evidence.result``
column. The dedicated ``files_read``/``files_changed``/``commands`` columns remain the
authoritative audit lists; the envelope carries everything else. The envelope never holds
a raw prompt, raw provider output, raw exception, host-absolute path, or a large artifact
payload — only repo-relative references, digests, and bounded scalars. ``from_result_json``
fails closed on an unknown schema version or a malformed/oversized document.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from ant_orchestrator.config.constants import (
    EVIDENCE_ENVELOPE_SCHEMA_VERSION,
    MAX_EVIDENCE_ENVELOPE_BYTES,
    MAX_PROVIDER_ID_CHARS,
)
from ant_orchestrator.core.domain.errors import InvariantViolation

__all__ = ["EvidenceEnvelope", "EvidenceEnvelopeError"]

_VERSION_KEY: Final = "evidence_schema_version"


class EvidenceEnvelopeError(InvariantViolation):
    """A persisted evidence envelope is malformed, oversized, or an unknown version."""


@dataclass(frozen=True, slots=True)
class EvidenceEnvelope:
    """Sanitized rich-reference bundle for one worker run (see module docstring)."""

    run_id: str
    logical_action_id: str
    attempt_id: str
    proposal_ref: str
    proposal_digest: str
    approval_ref: str
    context_package_ref: str
    manifest_digest: str
    protected_policy_version: int
    permission_decision: str
    receipt_ref: str
    receipt_status: str
    draft_digest: str
    energy_estimate_tokens: int
    energy_reservation_ref: str
    energy_actual_tokens: int
    energy_fallback_used: bool
    energy_over_budget: bool
    energy_settlement_ref: str
    journal_ref: str
    journal_status: str
    target_digest: str
    validation_result: str
    before_ref: str = ""
    proposed_ref: str = ""
    diff_ref: str = ""
    adapter_provider: str = ""
    model_id: str = ""

    def __post_init__(self) -> None:
        for name in ("run_id", "logical_action_id", "attempt_id", "proposal_digest"):
            if not getattr(self, name):
                raise EvidenceEnvelopeError(f"EvidenceEnvelope.{name} must be non-empty")
        for name in ("adapter_provider", "model_id"):
            if len(getattr(self, name)) > MAX_PROVIDER_ID_CHARS:
                raise EvidenceEnvelopeError(f"EvidenceEnvelope.{name} exceeds the bound")

    def _payload(self) -> dict[str, object]:
        body = {
            "run_id": self.run_id,
            "logical_action_id": self.logical_action_id,
            "attempt_id": self.attempt_id,
            "proposal_ref": self.proposal_ref,
            "proposal_digest": self.proposal_digest,
            "approval_ref": self.approval_ref,
            "context_package_ref": self.context_package_ref,
            "manifest_digest": self.manifest_digest,
            "protected_policy_version": self.protected_policy_version,
            "permission_decision": self.permission_decision,
            "receipt_ref": self.receipt_ref,
            "receipt_status": self.receipt_status,
            "draft_digest": self.draft_digest,
            "energy_estimate_tokens": self.energy_estimate_tokens,
            "energy_reservation_ref": self.energy_reservation_ref,
            "energy_actual_tokens": self.energy_actual_tokens,
            "energy_fallback_used": self.energy_fallback_used,
            "energy_over_budget": self.energy_over_budget,
            "energy_settlement_ref": self.energy_settlement_ref,
            "journal_ref": self.journal_ref,
            "journal_status": self.journal_status,
            "target_digest": self.target_digest,
            "validation_result": self.validation_result,
            "before_ref": self.before_ref,
            "proposed_ref": self.proposed_ref,
            "diff_ref": self.diff_ref,
            "adapter_provider": self.adapter_provider,
            "model_id": self.model_id,
        }
        return {_VERSION_KEY: EVIDENCE_ENVELOPE_SCHEMA_VERSION, **body}

    def to_result_json(self) -> str:
        """Canonical, bounded JSON for the ``evidence.result`` column."""
        document = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        if len(document.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
            raise EvidenceEnvelopeError("evidence envelope exceeds the size limit")
        return document

    def matches(self, other: EvidenceEnvelope) -> bool:
        """Structural equality used by compare-and-verify reconciliation."""
        return self._payload() == other._payload()

    @classmethod
    def from_result_json(cls, raw: str | None) -> EvidenceEnvelope:
        """Parse + validate a persisted envelope; fail closed on any inconsistency."""
        if raw is None:
            raise EvidenceEnvelopeError("evidence result is empty")
        if len(raw.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
            raise EvidenceEnvelopeError("evidence envelope exceeds the size limit")
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise EvidenceEnvelopeError("evidence envelope is not valid JSON") from exc
        if not isinstance(document, dict):
            raise EvidenceEnvelopeError("evidence envelope is not an object")
        if document.get(_VERSION_KEY) != EVIDENCE_ENVELOPE_SCHEMA_VERSION:
            raise EvidenceEnvelopeError("unsupported evidence envelope schema version")
        body = {k: v for k, v in document.items() if k != _VERSION_KEY}
        try:
            return cls(**body)
        except (TypeError, InvariantViolation) as exc:
            raise EvidenceEnvelopeError("evidence envelope has unexpected fields") from exc
