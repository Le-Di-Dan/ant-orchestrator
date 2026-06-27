"""Provider-neutral documentation composer contract (PHASE_5_PLAN CP5).

The composer is the ONLY boundary through which a model produces proposed document
content. It is deliberately free of any provider/SDK type and of any execution
authority: it receives a semantic ``DocumentationTask``, a *verified* context view,
and bounded constraints, and returns a :class:`CompositionResult` carrying ONLY a
typed :class:`ModelCompositionDraft`, sanitized usage, and sanitized provider/model
identifiers — never a raw provider response, prompt, or exception.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.document_worker import (
    MAX_PROPOSED_CONTENT_CHARS as _MAX_CONTENT,
)
from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    ModelCompositionDraft,
)
from ant_orchestrator.application.ports.llm import ModelUsage
from ant_orchestrator.core.domain.errors import InvariantViolation


@dataclass(frozen=True, slots=True)
class ComposerSource:
    """A single sanitized context source the composer may ground its draft on."""

    path: str
    content: str


@dataclass(frozen=True, slots=True)
class ComposerContext:
    """The verified, manifest-bound context view handed to the composer (I5).

    ``manifest_digest`` binds this view to the persisted, verified context package;
    the composer never reads the filesystem or anything outside ``sources``.
    """

    manifest_digest: str
    sources: tuple[ComposerSource, ...]

    def __post_init__(self) -> None:
        if not self.manifest_digest:
            raise InvariantViolation("ComposerContext.manifest_digest must be non-empty")


@dataclass(frozen=True, slots=True)
class CompositionConstraints:
    """Bounded constraints the composer/parser must respect (no authority)."""

    max_content_chars: int = _MAX_CONTENT

    def __post_init__(self) -> None:
        if self.max_content_chars < 1:
            raise InvariantViolation("CompositionConstraints.max_content_chars must be >= 1")


@dataclass(frozen=True, slots=True)
class CompositionResult:
    """A composer's sanitized output — typed draft + usage + provider identity.

    Carries NO raw provider envelope, NO prompt, NO exception. ``provider_id`` and
    ``model_id`` are sanitized adapter-reported identifiers (may be ``None`` if a
    policy forbids exposing them).
    """

    draft: ModelCompositionDraft
    usage: ModelUsage
    provider_id: str | None
    model_id: str | None
    prompt_template_id: str
    prompt_template_version: int


@runtime_checkable
class DocumentationComposer(Protocol):
    """Async, provider-neutral composition boundary the Documentation Ant depends on."""

    async def compose(
        self,
        task: DocumentationTask,
        context: ComposerContext,
        constraints: CompositionConstraints,
    ) -> CompositionResult:
        """Produce a typed draft from the task and verified context, or raise.

        Raises a sanitized error (composition parse failure, prohibited model field,
        or a provider :class:`~ant_orchestrator.application.ports.llm_errors.AdapterError`).
        """
        ...
