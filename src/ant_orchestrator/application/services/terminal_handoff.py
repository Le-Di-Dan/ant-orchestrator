"""TerminalHandoffService — create a bounded, idempotent terminal handoff (CP5).

For every terminal workflow outcome (completed, failed, rejected, cancelled, and budget/retry
exhaustion mapped to ``failed``) this service assembles a :class:`TerminalHandoffPayload`
envelope and persists it in ``handoff_records``.  The ``HandoffId`` is deterministic so
replay after a crash is an idempotent no-op (find → existing, return same id).

The handoff NEVER contains raw test output, tracebacks, exceptions, host paths or secrets.
Only bounded, sanitized references and deterministic next-action strings are persisted.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from ant_orchestrator.config.constants import (
    MAX_TERMINAL_HANDOFF_BYTES,
    TERMINAL_HANDOFF_SCHEMA_VERSION,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.records import HandoffRecord
from ant_orchestrator.core.domain.value_objects import HandoffId, TaskId, UtcTimestamp
from ant_orchestrator.core.ports.clock import Clock

__all__ = ["HandoffRepository", "TerminalHandoffPayloadError", "TerminalHandoffService"]

_ID_SEP: Final = "\x00"


@runtime_checkable
class HandoffRepository(Protocol):
    """Minimal persistence port for terminal handoffs (application-layer view)."""

    def find(self, handoff_id: HandoffId) -> HandoffRecord | None: ...

    def append(self, handoff: HandoffRecord) -> None: ...


_SCHEMA_KEY: Final = "handoff_schema_version"

# Deterministic recommended next actions — bounded, no raw command/fix advice.
_NEXT_ACTIONS: dict[str, str] = {
    "completed": "Archive task; no further automated action required.",
    "failed": "Queue for Queen review of failure evidence and energy report.",
    "rejected": "Route task to queue for re-specification or cancellation.",
    "cancelled": "Record cancellation event and archive; no retry is performed.",
}
_DEFAULT_NEXT = "Escalate to Queen for manual intervention."


class TerminalHandoffPayloadError(InvariantViolation):
    """Terminal handoff payload is malformed, oversized, or an unknown version."""


@dataclass(frozen=True, slots=True)
class TerminalHandoffPayload:
    """Bounded, sanitized terminal handoff payload stored in handoff_records.what_changed."""

    run_ref: str
    task_ref: str
    final_status: str
    terminal_phase: str
    retry_count: int
    retry_extension_count: int
    regroup_count: int
    test_attempt_ref: str | None
    test_result: str | None
    failure_category: str | None
    failure_reason_code: str | None
    failure_disposition: str | None
    evidence_refs: tuple[str, ...]
    context_manifest_digest: str | None
    approval_decision: str | None
    cancellation_info: str | None
    created_at: str

    def __post_init__(self) -> None:
        for name in ("run_ref", "task_ref", "final_status", "created_at"):
            if not getattr(self, name):
                raise TerminalHandoffPayloadError(
                    f"TerminalHandoffPayload.{name} must be non-empty"
                )

    def _body(self) -> dict[str, object]:
        return {
            _SCHEMA_KEY: TERMINAL_HANDOFF_SCHEMA_VERSION,
            "run_ref": self.run_ref,
            "task_ref": self.task_ref,
            "final_status": self.final_status,
            "terminal_phase": self.terminal_phase,
            "retry_count": self.retry_count,
            "retry_extension_count": self.retry_extension_count,
            "regroup_count": self.regroup_count,
            "test_attempt_ref": self.test_attempt_ref,
            "test_result": self.test_result,
            "failure_category": self.failure_category,
            "failure_reason_code": self.failure_reason_code,
            "failure_disposition": self.failure_disposition,
            "evidence_refs": list(self.evidence_refs),
            "context_manifest_digest": self.context_manifest_digest,
            "approval_decision": self.approval_decision,
            "cancellation_info": self.cancellation_info,
            "created_at": self.created_at,
        }

    def to_json(self) -> str:
        document = json.dumps(self._body(), sort_keys=True, separators=(",", ":"))
        if len(document.encode("utf-8")) > MAX_TERMINAL_HANDOFF_BYTES:
            raise TerminalHandoffPayloadError("terminal handoff payload exceeds the size limit")
        return document

    @classmethod
    def from_json(cls, raw: str | None) -> TerminalHandoffPayload:
        if raw is None:
            raise TerminalHandoffPayloadError("terminal handoff payload is empty")
        if len(raw.encode("utf-8")) > MAX_TERMINAL_HANDOFF_BYTES:
            raise TerminalHandoffPayloadError("terminal handoff payload exceeds the size limit")
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TerminalHandoffPayloadError("terminal handoff payload is not valid JSON") from exc
        if not isinstance(doc, dict):
            raise TerminalHandoffPayloadError("terminal handoff payload is not an object")
        if doc.get(_SCHEMA_KEY) != TERMINAL_HANDOFF_SCHEMA_VERSION:
            raise TerminalHandoffPayloadError("unsupported terminal handoff schema version")
        try:
            body = {k: v for k, v in doc.items() if k != _SCHEMA_KEY}
            if "evidence_refs" in body:
                body["evidence_refs"] = tuple(body["evidence_refs"])
            return cls(**body)
        except (TypeError, InvariantViolation) as exc:
            raise TerminalHandoffPayloadError(
                "terminal handoff payload has unexpected fields"
            ) from exc


class TerminalHandoffService:
    """Assemble and persist a terminal handoff record; idempotent on replay."""

    def __init__(
        self,
        handoff_repository: HandoffRepository,
        *,
        clock: Clock,
    ) -> None:
        self._repo = handoff_repository
        self._clock = clock

    def create_terminal_handoff(
        self,
        *,
        run_id: str,
        task_id: str,
        final_outcome: str,
        state: Mapping[str, object],
    ) -> str:
        """Create (or reuse) the terminal handoff for this run; return the handoff_id."""
        hid = HandoffId(_terminal_handoff_id(run_id, final_outcome))
        existing = self._repo.find(hid)
        if existing is not None:
            return hid.value

        now = self._clock.now()
        payload = _build_payload(run_id, task_id, final_outcome, state, now)
        payload_json = payload.to_json()
        summary = _build_summary(final_outcome, run_id)
        next_steps = _NEXT_ACTIONS.get(final_outcome, _DEFAULT_NEXT)
        record = HandoffRecord(
            id=hid,
            task_id=TaskId(task_id),
            summary=summary,
            created_at=now,
            what_changed=payload_json,
            next_steps=next_steps,
        )
        self._repo.append(record)
        return hid.value


def _build_payload(
    run_id: str,
    task_id: str,
    final_outcome: str,
    state: Mapping[str, object],
    now: UtcTimestamp,
) -> TerminalHandoffPayload:
    evidence_refs_raw = state.get("test_evidence_refs") or []
    if not isinstance(evidence_refs_raw, list):
        evidence_refs_raw = []
    # Only keep str refs — never let non-str values slip through.
    evidence_refs = tuple(str(r) for r in evidence_refs_raw if isinstance(r, str))

    # Approval decision from resolved approval_decision field (JSON-safe str or None).
    approval_decision_raw = state.get("approval_decision")
    if isinstance(approval_decision_raw, dict):
        approval_decision = str(approval_decision_raw.get("decision") or "")[:80] or None
    else:
        approval_decision = None

    # Cancellation info — only for cancelled outcome.
    cancellation_info: str | None = None
    if final_outcome == "cancelled":
        error_summary = state.get("error_summary")
        if isinstance(error_summary, str) and error_summary:
            cancellation_info = error_summary[:120]

    return TerminalHandoffPayload(
        run_ref=run_id,
        task_ref=task_id,
        final_status=final_outcome,
        terminal_phase=str(state.get("phase") or "unknown"),
        retry_count=_to_int(state.get("retry_count")),
        retry_extension_count=_to_int(state.get("retry_extension_count")),
        regroup_count=_to_int(state.get("regroup_count")),
        test_attempt_ref=_str_or_none(state.get("test_attempt_ref")),
        test_result=_str_or_none(state.get("test_outcome")),
        failure_category=_str_or_none(state.get("test_failure_category")),
        failure_reason_code=_str_or_none(state.get("test_reason_code")),
        failure_disposition=_str_or_none(state.get("test_recovery_disposition")),
        evidence_refs=evidence_refs,
        context_manifest_digest=_str_or_none(state.get("context_manifest_digest")),
        approval_decision=approval_decision,
        cancellation_info=cancellation_info,
        created_at=now.to_iso(),
    )


def _terminal_handoff_id(run_id: str, final_outcome: str) -> str:
    """Deterministic SHA-256 id for a terminal handoff (mirrors integration.identity semantics)."""
    seed = _ID_SEP.join(("terminal_handoff", run_id, final_outcome))
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _build_summary(final_outcome: str, run_id: str) -> str:
    short_id = run_id[:12] if len(run_id) > 12 else run_id
    return f"Terminal handoff: {final_outcome} (run: {short_id})"


def _str_or_none(value: object) -> str | None:
    if value is None:
        return None
    s = str(value)
    return s if s else None


def _to_int(value: object) -> int:
    if isinstance(value, int):
        return value
    if value is None:
        return 0
    try:
        return int(str(value))
    except (ValueError, TypeError):
        return 0
