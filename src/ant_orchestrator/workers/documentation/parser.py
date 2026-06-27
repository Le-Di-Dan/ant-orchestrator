"""Strict, sanitizing parser: raw model output → ``ModelCompositionDraft`` (CP5 / §3).

The model is authoritative ONLY for content. The parser therefore accepts a closed
set of content keys and REJECTS (fail-closed) any output that tries to declare an
operational fact (target, operation, files, commands, evidence, result, permission,
energy). It never lets raw provider output flow into an exception message: a parse
failure reports a generic reason; a prohibited field is named from a FIXED vocabulary.
The parser performs no filesystem access and produces no operational facts.
"""

from __future__ import annotations

import json
from typing import Final

from ant_orchestrator.application.ports.document_worker import (
    MAX_REPORT_ITEMS,
    ModelCompositionDraft,
)
from ant_orchestrator.application.ports.documentation_composer import CompositionConstraints
from ant_orchestrator.config.constants import MAX_MODEL_OUTPUT_CHARS
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.workers.documentation.errors import (
    CompositionParseError,
    ProhibitedModelFieldError,
)

_CONTENT_KEY: Final = "proposed_content"
_ALLOWED_KEYS: Final[frozenset[str]] = frozenset({_CONTENT_KEY, "summary", "risks", "next_steps"})
# Operational fields a model must never declare (I2). Named explicitly so an
# adversarial output is rejected with a stable, sanitized field name.
_PROHIBITED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "target",
        "target_document",
        "path",
        "operation",
        "allowed_paths",
        "files_read",
        "files_changed",
        "commands",
        "command",
        "diff",
        "evidence",
        "evidence_refs",
        "permission",
        "policy_version",
        "energy",
        "energy_usage",
        "usage",
        "result",
        "success",
        "outcome",
    }
)


def parse_model_output(raw: str, constraints: CompositionConstraints) -> ModelCompositionDraft:
    """Parse a JSON object of content fields into a typed draft, or fail closed."""
    if len(raw) > MAX_MODEL_OUTPUT_CHARS:
        raise CompositionParseError("model output exceeds the parse bound")
    try:
        document = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        raise CompositionParseError("model output is not valid JSON") from None
    if not isinstance(document, dict):
        raise CompositionParseError("model output is not a JSON object")

    for key in document:
        if not isinstance(key, str):
            raise CompositionParseError("model output has a non-string key")
        if key in _PROHIBITED_KEYS:
            raise ProhibitedModelFieldError(key)
        if key not in _ALLOWED_KEYS:
            # Strict typed policy: unknown keys are rejected (no raw key echoed).
            raise CompositionParseError("model output has an unexpected field")

    content = document.get(_CONTENT_KEY)
    if not isinstance(content, str) or not content:
        raise CompositionParseError("model output is missing required proposed_content")
    if len(content) > constraints.max_content_chars:
        raise CompositionParseError("proposed_content exceeds the content bound")

    summary = _optional_str(document.get("summary"), "summary")
    risks = _str_tuple(document.get("risks"), "risks")
    next_steps = _str_tuple(document.get("next_steps"), "next_steps")
    try:
        return ModelCompositionDraft(
            proposed_content=content,
            summary=summary,
            risks=risks,
            next_steps=next_steps,
        )
    except InvariantViolation:
        raise CompositionParseError("model output violates a draft bound") from None


def _optional_str(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CompositionParseError(f"model output {field} must be a string")
    return value


def _str_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or len(value) > MAX_REPORT_ITEMS:
        raise CompositionParseError(f"model output {field} must be a bounded list")
    items: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise CompositionParseError(f"model output {field} entries must be strings")
        items.append(entry)
    return tuple(items)
