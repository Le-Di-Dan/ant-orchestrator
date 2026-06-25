"""Deterministic context selection — pure logic, no I/O (CP5).

Selects and rejects artifact candidates based on budget, exclusions, and
eligibility. No filesystem access, no repository scanning, no semantic ranking.
Selection order: REQUIRED first, then OPTIONAL, stable within group by
original request order. Greedy: skip optional that doesn't fit, try next.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ContextBudget,
)
from ant_orchestrator.context.budget import BudgetTracker, BudgetUsage
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


class SelectionReason(Enum):
    """Why an artifact was selected."""

    REQUESTED_REQUIRED = "requested_required"
    REQUESTED_OPTIONAL = "requested_optional"


class RejectionReason(Enum):
    """Why an artifact was rejected."""

    OUTSIDE_SCOPE = "outside_scope"
    EXCLUDED = "excluded"
    BINARY = "binary"
    OVERSIZED = "oversized"
    SECRET_FILE = "secret_file"
    BUDGET_EXCEEDED = "budget_exceeded"
    INVALID_REQUEST = "invalid_request"


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    """Pre-resolved candidate with metadata. Created by CP6, consumed by selector."""

    request: ArtifactRequest
    estimated_tokens: TokenCount
    eligible: bool
    rejection_reason: RejectionReason | None
    original_order: int

    def __post_init__(self) -> None:
        if self.eligible and self.rejection_reason is not None:
            raise InvariantViolation("Eligible candidate must not have a rejection reason")
        if not self.eligible and self.rejection_reason is None:
            raise InvariantViolation("Ineligible candidate must have a rejection reason")
        if self.original_order < 0:
            raise InvariantViolation("original_order must be >= 0")


@dataclass(frozen=True, slots=True)
class SelectedArtifact:
    """An artifact that passed selection and will be included in context."""

    path: str
    estimated_tokens: TokenCount
    reason: SelectionReason


@dataclass(frozen=True, slots=True)
class RejectedArtifact:
    """An artifact that was rejected with a typed reason."""

    path: str
    reason: RejectionReason


@dataclass(frozen=True, slots=True)
class ContextSelectionResult:
    """Immutable selection outcome — enough for CP6 to build manifest."""

    selected: tuple[SelectedArtifact, ...]
    rejected: tuple[RejectedArtifact, ...]
    budget_initial: ContextBudget
    budget_used: BudgetUsage
    budget_remaining: BudgetUsage
    required_failure: bool


class ContextSelector:
    """Pure, deterministic artifact selection against a budget.

    Does not access the filesystem, scan directories, or discover artifacts.
    All candidates must be provided explicitly via the ``candidates`` argument.
    """

    def select(
        self,
        candidates: tuple[ArtifactCandidate, ...],
        excluded: frozenset[str],
        budget: ContextBudget,
    ) -> ContextSelectionResult:
        deduped = _deduplicate(candidates)
        tracker = BudgetTracker(budget)
        selected: list[SelectedArtifact] = []
        rejected: list[RejectedArtifact] = []
        required_failure = False

        ordered = sorted(
            deduped,
            key=lambda c: (
                0 if c.request.requirement is ArtifactRequirement.REQUIRED else 1,
                c.original_order,
            ),
        )

        for candidate in ordered:
            path = candidate.request.path
            is_required = candidate.request.requirement is ArtifactRequirement.REQUIRED

            if path in excluded:
                rejected.append(RejectedArtifact(path, RejectionReason.EXCLUDED))
                if is_required:
                    required_failure = True
                continue

            if not candidate.eligible:
                assert candidate.rejection_reason is not None
                rejected.append(RejectedArtifact(path, candidate.rejection_reason))
                if is_required:
                    required_failure = True
                continue

            if not tracker.can_fit(candidate.estimated_tokens):
                rejected.append(RejectedArtifact(path, RejectionReason.BUDGET_EXCEEDED))
                if is_required:
                    required_failure = True
                continue

            reason = (
                SelectionReason.REQUESTED_REQUIRED
                if is_required
                else SelectionReason.REQUESTED_OPTIONAL
            )
            tracker.consume(candidate.estimated_tokens)
            selected.append(SelectedArtifact(path, candidate.estimated_tokens, reason))

        return ContextSelectionResult(
            selected=tuple(selected),
            rejected=tuple(rejected),
            budget_initial=budget,
            budget_used=tracker.usage,
            budget_remaining=tracker.remaining(),
            required_failure=required_failure,
        )


def _deduplicate(
    candidates: tuple[ArtifactCandidate, ...],
) -> list[ArtifactCandidate]:
    """Merge duplicate paths: REQUIRED wins over OPTIONAL. Keep earliest order."""
    seen: dict[str, ArtifactCandidate] = {}
    for c in candidates:
        path = c.request.path
        if path not in seen:
            seen[path] = c
            continue
        existing = seen[path]
        if (
            c.request.requirement is ArtifactRequirement.REQUIRED
            and existing.request.requirement is ArtifactRequirement.OPTIONAL
        ):
            seen[path] = ArtifactCandidate(
                request=ArtifactRequest(path, ArtifactRequirement.REQUIRED),
                estimated_tokens=c.estimated_tokens,
                eligible=c.eligible,
                rejection_reason=c.rejection_reason,
                original_order=existing.original_order,
            )
    return list(seen.values())
