"""Versioned test-evidence envelope stored in ``execution_evidence.result`` (CP5).

The Test Ant does not produce a proposal/approval/receipt chain; its evidence envelope
(version 2) only stores what the Test Ant can observe: the sanitized, bounded
:class:`StructuredTestReport` payload plus context/scope digests for replay identity.
Version 1 is the DocAnt envelope — a different class; the version key is the
discriminant. ``from_result_json`` fails closed on any version mismatch.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Final

from ant_orchestrator.config.constants import (
    MAX_EVIDENCE_ENVELOPE_BYTES,
    TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION,
)
from ant_orchestrator.core.domain.errors import InvariantViolation

__all__ = ["TestEvidenceEnvelope", "TestEvidenceEnvelopeError"]

_VERSION_KEY: Final = "evidence_schema_version"
_KIND: Final = "test_execution"


class TestEvidenceEnvelopeError(InvariantViolation):
    """A persisted test evidence envelope is malformed, oversized, or unknown version."""


@dataclass(frozen=True, slots=True)
class TestEvidenceEnvelope:
    """Sanitized, versioned evidence for one Test Ant attempt.

    The ``report_payload`` is the JSON-safe dict produced by
    :meth:`StructuredTestReport.to_state_dict` — bounded, no raw output/host path.
    ``context_manifest_digest`` and ``read_scope_digest`` are the approved digests
    that bound this evidence to its workflow context (idempotency + audit).
    """

    run_ref: str
    logical_action_ref: str
    attempt_ref: str
    worker_kind: str
    context_manifest_digest: str
    read_scope_digest: str
    report_payload: dict[str, object]
    created_at: str

    def __post_init__(self) -> None:
        for name in ("run_ref", "logical_action_ref", "attempt_ref", "worker_kind", "created_at"):
            if not getattr(self, name):
                raise TestEvidenceEnvelopeError(f"TestEvidenceEnvelope.{name} must be non-empty")
        if not isinstance(self.report_payload, dict):
            raise TestEvidenceEnvelopeError("TestEvidenceEnvelope.report_payload must be a dict")

    def _payload(self) -> dict[str, object]:
        return {
            _VERSION_KEY: TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION,
            "evidence_kind": _KIND,
            "run_ref": self.run_ref,
            "logical_action_ref": self.logical_action_ref,
            "attempt_ref": self.attempt_ref,
            "worker_kind": self.worker_kind,
            "context_manifest_digest": self.context_manifest_digest,
            "read_scope_digest": self.read_scope_digest,
            "created_at": self.created_at,
            "report": self.report_payload,
        }

    def to_result_json(self) -> str:
        """Canonical, bounded JSON for the ``execution_evidence.result`` column."""
        document = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        if len(document.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
            raise TestEvidenceEnvelopeError("test evidence envelope exceeds the size limit")
        return document

    def matches(self, other: TestEvidenceEnvelope) -> bool:
        """Structural equality used by compare-and-verify reconciliation.

        ``created_at`` is a wall-clock stamp set on first write and is excluded
        from identity comparison so a replay with a fresh timestamp still matches.
        """
        _SKIP = {"created_at"}
        p_self = {k: v for k, v in self._payload().items() if k not in _SKIP}
        p_other = {k: v for k, v in other._payload().items() if k not in _SKIP}
        return p_self == p_other

    @classmethod
    def from_result_json(cls, raw: str | None) -> TestEvidenceEnvelope:
        """Parse + validate a persisted envelope; fail closed on any inconsistency."""
        if raw is None:
            raise TestEvidenceEnvelopeError("test evidence result is empty")
        if len(raw.encode("utf-8")) > MAX_EVIDENCE_ENVELOPE_BYTES:
            raise TestEvidenceEnvelopeError("test evidence envelope exceeds the size limit")
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TestEvidenceEnvelopeError("test evidence envelope is not valid JSON") from exc
        if not isinstance(document, dict):
            raise TestEvidenceEnvelopeError("test evidence envelope is not an object")
        if document.get(_VERSION_KEY) != TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION:
            raise TestEvidenceEnvelopeError("unsupported test evidence envelope schema version")
        if document.get("evidence_kind") != _KIND:
            raise TestEvidenceEnvelopeError("unexpected evidence_kind in test evidence envelope")
        try:
            body = {k: v for k, v in document.items() if k not in (_VERSION_KEY, "evidence_kind")}
            # Rename serialised key "report" back to the field name "report_payload".
            if "report" in body:
                body["report_payload"] = body.pop("report")
            return cls(**body)
        except (TypeError, InvariantViolation) as exc:
            raise TestEvidenceEnvelopeError("test evidence envelope has unexpected fields") from exc
