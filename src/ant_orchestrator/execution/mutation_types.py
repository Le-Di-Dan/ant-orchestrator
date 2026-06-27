"""Typed inputs/outputs for the safe document mutator (PHASE_5_PLAN CP4).

The request carries authority that originates from ``ApprovedExecutionScope`` plus the
raw approved target string — never a model-chosen path. The result is system-assembled:
canonical target, artifact references + digests, target digest, and journal reference.
Exactly one target per request (there is no batch API).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.application.ports.document_worker import DocumentOperation


@dataclass(frozen=True, slots=True)
class MutationRequest:
    """A single-target CREATE/UPDATE request with its execution authority."""

    run_id: str
    attempt_id: str
    logical_action_id: str
    proposal_digest: str
    context_digest: str
    approval_ref: str
    requested_target: str
    operation: DocumentOperation
    proposed_content: str
    required_sections: tuple[str, ...]
    protected_policy_version: int


class MutationOutcome(Enum):
    """The boundary outcome of a CP4 mutation (SUCCESS/COMPLETED is CP6, after DB)."""

    PUBLISHED = "published"
    NO_CHANGE = "no_change"
    PERMISSION_DENIED = "permission_denied"
    PERMISSION_DECISION_INVALID = "permission_decision_invalid"
    VALIDATION_FAILED = "validation_failed"
    TARGET_EXISTS = "target_exists"
    TARGET_MISSING = "target_missing"
    TARGET_NOT_FILE = "target_not_file"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class MutationResult:
    """System-assembled mutation outcome + durable references (no raw payload/error)."""

    outcome: MutationOutcome
    operation: str
    protected_policy_version: int
    canonical_target: str | None = None
    before_kind: str | None = None
    before_ref: str | None = None
    before_digest: str | None = None
    proposed_ref: str | None = None
    proposed_digest: str | None = None
    diff_ref: str | None = None
    diff_digest: str | None = None
    target_digest: str | None = None
    journal_ref: str | None = None
    journal_status: str | None = None
    permission_reason: str | None = None
    validation_failures: tuple[str, ...] = ()

    @property
    def published(self) -> bool:
        return self.outcome is MutationOutcome.PUBLISHED
