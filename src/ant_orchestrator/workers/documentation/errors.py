"""Sanitized error taxonomy for the Documentation Ant provider phase (CP5).

Every error derives from ``DomainError`` and carries only a stable, sanitized message
plus an optional typed field name drawn from a FIXED vocabulary — never raw provider
output, a prompt, a stack trace, or a model-chosen key.
"""

from __future__ import annotations

from ant_orchestrator.core.domain.errors import DomainError


class DocumentationError(DomainError):
    """Base class for Documentation Ant composition/receipt failures (fail-closed)."""


class CompositionParseError(DocumentationError):
    """The model output could not be parsed into a typed draft (no raw output echoed)."""


class ProhibitedModelFieldError(DocumentationError):
    """The model output declared a prohibited operational field (named from a fixed set)."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"model output declared prohibited operational field: {field}")


class CompositionReceiptCorrupt(DocumentationError):
    """The composition receipt is missing, malformed, or fails its checksum."""


class UnsupportedReceiptVersion(DocumentationError):
    """The composition receipt schema version is not supported by this code."""


class InvalidReceiptTransition(DocumentationError):
    """A receipt status transition is backward or skips a required state."""


class CompositionIdentityConflict(DocumentationError):
    """A receipt shares this identity but binds a different draft digest."""
