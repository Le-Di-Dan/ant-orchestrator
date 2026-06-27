"""Production documentation composer over the provider-neutral ``LLMAdapter`` (CP5).

Builds the prompt, calls the adapter, and parses the reply into a typed draft. It
exposes only sanitized outputs: the typed draft, the adapter's normalized usage, and
the adapter's neutral provider/model identifiers (bounded). The raw response text is
consumed by the parser and then discarded — it is never returned, persisted, or logged.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.document_worker import DocumentationTask
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    CompositionConstraints,
    CompositionResult,
)
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.config.constants import MAX_PROVIDER_ID_CHARS
from ant_orchestrator.workers.documentation.parser import parse_model_output
from ant_orchestrator.workers.documentation.prompt import DocumentationPromptBuilder


class LLMDocumentationComposer:
    """A ``DocumentationComposer`` backed by an injected ``LLMAdapter``."""

    def __init__(
        self,
        adapter: LLMAdapter,
        *,
        prompt_builder: DocumentationPromptBuilder | None = None,
    ) -> None:
        self._adapter = adapter
        self._prompts = (
            prompt_builder if prompt_builder is not None else DocumentationPromptBuilder()
        )

    async def compose(
        self,
        task: DocumentationTask,
        context: ComposerContext,
        constraints: CompositionConstraints,
    ) -> CompositionResult:
        request = self._prompts.build(task, context, constraints)
        response = await self._adapter.complete(request)
        draft = parse_model_output(response.text, constraints)
        return CompositionResult(
            draft=draft,
            usage=response.usage,
            provider_id=_sanitize(response.provider),
            model_id=_sanitize(response.model),
            prompt_template_id=self._prompts.template_id,
            prompt_template_version=self._prompts.template_version,
        )


def _sanitize(identifier: str | None) -> str | None:
    """Bound a neutral provider/model identifier; reject embedded control characters."""
    if identifier is None:
        return None
    cleaned = "".join(ch for ch in identifier if ch.isprintable())
    return cleaned[:MAX_PROVIDER_ID_CHARS]
