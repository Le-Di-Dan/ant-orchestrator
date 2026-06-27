"""Prompt construction for documentation composition (PHASE_5_PLAN CP5 / §2).

Builds an ``LLMRequest`` from the semantic task and the VERIFIED context view only —
never the repository, never paths outside the manifest, never secrets or execution
evidence. The raw prompt exists only in memory for the duration of the call: only the
stable template id/version is ever persisted (in the receipt), never the prompt content.
The system prompt instructs the model to return content-only JSON and to respect frozen
documents, but the model's reply is treated as non-authoritative regardless.
"""

from __future__ import annotations

import json

from ant_orchestrator.application.ports.document_worker import DocumentationTask
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    CompositionConstraints,
)
from ant_orchestrator.application.ports.llm import LLMMessage, LLMRequest, MessageRole
from ant_orchestrator.config.constants import DOC_PROMPT_TEMPLATE_ID, DOC_PROMPT_TEMPLATE_VERSION

_SYSTEM_INSTRUCTION = (
    "You are a documentation composer. Return ONLY a JSON object with keys "
    '"proposed_content" (required string), "summary" (optional string), "risks" '
    '(optional list of strings), and "next_steps" (optional list of strings). Do not '
    "include any other key. Do not decide file paths, operations, permissions, "
    "commands, or results — those are governed by the system, not by you. Never modify "
    "or contradict frozen foundation documents."
)


class DocumentationPromptBuilder:
    """Stateless builder turning a task + verified context into an ``LLMRequest``."""

    @property
    def template_id(self) -> str:
        return DOC_PROMPT_TEMPLATE_ID

    @property
    def template_version(self) -> int:
        return DOC_PROMPT_TEMPLATE_VERSION

    def build(
        self,
        task: DocumentationTask,
        context: ComposerContext,
        constraints: CompositionConstraints,
    ) -> LLMRequest:
        """Render the provider request; content stays in memory only."""
        instruction = {
            "operation": task.operation.value,
            "purpose": task.expected_document_purpose,
            "instruction_summary": task.instruction_summary,
            "required_sections": list(task.required_sections),
            "max_content_chars": constraints.max_content_chars,
            "context": [
                {"path": source.path, "content": source.content} for source in context.sources
            ],
        }
        user = LLMMessage(
            role=MessageRole.USER,
            content=json.dumps(instruction, ensure_ascii=False, sort_keys=True),
        )
        return LLMRequest(messages=(user,), system_prompt=_SYSTEM_INSTRUCTION)
