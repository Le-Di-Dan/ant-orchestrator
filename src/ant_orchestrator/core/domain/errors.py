"""Domain-layer errors (see PHASE_1_PLAN §14).

The domain owns only domain rules; configuration, workspace and persistence
errors live in their own layers.
"""

from __future__ import annotations

from ant_orchestrator.errors import AntError


class DomainError(AntError):
    """Base class for domain-rule violations."""


class InvariantViolation(DomainError):
    """A domain value or entity invariant was violated."""


class InvalidStatusValue(DomainError):
    """A status string does not map to a known enum member."""


class ApprovalAlreadyResolved(DomainError):
    """An attempt was made to resolve an Approval that is no longer pending."""
