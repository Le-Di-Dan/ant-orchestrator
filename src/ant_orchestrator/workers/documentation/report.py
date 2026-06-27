"""Authoritative worker result + report assembly (PHASE_5_PLAN CP5 / §12).

The ``WorkerExecutionReport`` is built ENTIRELY from system facts: the context
manifest (files_read), the ``MutationResult`` (files_changed), the empty command
audit (CP5 runs no shell), and a system-derived ``result``. Only ``summary``/``risks``/
``next_steps`` may incorporate *sanitized* draft metadata — never an operational fact.
This module also owns the typed draft (de)serialization for the durable draft artifact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.application.ports.document_worker import (
    ModelCompositionDraft,
    WorkerExecutionReport,
)
from ant_orchestrator.application.ports.worker import MAX_WORKER_DETAIL_CHARS, WorkerOutcome
from ant_orchestrator.workers.documentation.errors import CompositionParseError
from ant_orchestrator.workers.documentation.parser import parse_model_output


class DocumentationStatus(Enum):
    """The Documentation Ant's controlled outcome (system-derived, not model-declared)."""

    PUBLISHED = "published"
    NO_CHANGE = "no_change"
    IDENTITY_INVALID = "identity_invalid"
    CONTEXT_FAILED = "context_failed"
    PERMISSION_DENIED = "permission_denied"
    ENERGY_DENIED = "energy_denied"
    COMPOSITION_FAILED = "composition_failed"
    IN_DOUBT = "in_doubt"
    OVER_BUDGET = "over_budget"
    SETTLEMENT_FAILED = "settlement_failed"
    VALIDATION_FAILED = "validation_failed"
    MUTATION_CONFLICT = "mutation_conflict"
    MUTATION_FAILED = "mutation_failed"


_OUTCOME: dict[DocumentationStatus, WorkerOutcome] = {
    DocumentationStatus.PUBLISHED: WorkerOutcome.SUCCESS,
    DocumentationStatus.NO_CHANGE: WorkerOutcome.SUCCESS,
    DocumentationStatus.IDENTITY_INVALID: WorkerOutcome.PERMANENT_FAILURE,
    DocumentationStatus.CONTEXT_FAILED: WorkerOutcome.PERMANENT_FAILURE,
    DocumentationStatus.PERMISSION_DENIED: WorkerOutcome.PERMANENT_FAILURE,
    DocumentationStatus.ENERGY_DENIED: WorkerOutcome.PERMANENT_FAILURE,
    DocumentationStatus.COMPOSITION_FAILED: WorkerOutcome.PERMANENT_FAILURE,
    DocumentationStatus.IN_DOUBT: WorkerOutcome.ESCALATION,
    DocumentationStatus.OVER_BUDGET: WorkerOutcome.ESCALATION,
    DocumentationStatus.SETTLEMENT_FAILED: WorkerOutcome.RETRYABLE_FAILURE,
    DocumentationStatus.VALIDATION_FAILED: WorkerOutcome.VALIDATION_FAILURE,
    DocumentationStatus.MUTATION_CONFLICT: WorkerOutcome.RETRYABLE_FAILURE,
    DocumentationStatus.MUTATION_FAILED: WorkerOutcome.PERMANENT_FAILURE,
}


@dataclass(frozen=True, slots=True)
class DocumentationResult:
    """Typed worker result: the §12 report + honest provider/receipt facts."""

    status: DocumentationStatus
    report: WorkerExecutionReport
    provider_invoked: bool
    failure_code: str | None = None
    receipt_status: str | None = None


def serialize_draft(draft: ModelCompositionDraft) -> str:
    """Serialize the typed draft for the durable draft artifact (no provider envelope)."""
    return json.dumps(
        {
            "proposed_content": draft.proposed_content,
            "summary": draft.summary,
            "risks": list(draft.risks),
            "next_steps": list(draft.next_steps),
        },
        ensure_ascii=False,
        sort_keys=True,
    )


def deserialize_draft(text: str) -> ModelCompositionDraft:
    """Rebuild the typed draft from a persisted draft artifact (strict, sanitized)."""
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        raise CompositionParseError("draft artifact is not valid JSON") from None
    if not isinstance(document, dict):
        raise CompositionParseError("draft artifact is not an object")
    summary = document.get("summary")
    payload = {
        "proposed_content": document.get("proposed_content"),
        "summary": summary if isinstance(summary, str) else None,
        "risks": document.get("risks") or [],
        "next_steps": document.get("next_steps") or [],
    }
    from ant_orchestrator.application.ports.documentation_composer import CompositionConstraints

    return parse_model_output(json.dumps(payload), CompositionConstraints())


def _sanitized_summary(draft: ModelCompositionDraft | None, fallback: str) -> str:
    if draft is not None and draft.summary:
        return draft.summary[:MAX_WORKER_DETAIL_CHARS]
    return fallback[:MAX_WORKER_DETAIL_CHARS]


def build_report(
    *,
    status: DocumentationStatus,
    summary_fallback: str,
    files_read: tuple[str, ...],
    files_changed: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    draft: ModelCompositionDraft | None,
) -> WorkerExecutionReport:
    """Assemble the §12 report from system facts plus sanitized draft metadata only."""
    success = status in (DocumentationStatus.PUBLISHED, DocumentationStatus.NO_CHANGE)
    risks = draft.risks if (success and draft is not None) else ()
    next_steps = draft.next_steps if (success and draft is not None) else ()
    return WorkerExecutionReport(
        summary=_sanitized_summary(draft if success else None, summary_fallback),
        files_read=files_read,
        files_changed=files_changed,
        commands=(),
        result=_OUTCOME[status],
        evidence_refs=evidence_refs,
        risks=risks,
        next_steps=next_steps,
    )
