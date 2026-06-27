"""Deterministic document validation — completes BEFORE publish (PHASE_5_PLAN CP4).

A structural guardrail only: it checks proposed content is non-empty, UTF-8-clean,
bounded, and that every required section is present exactly once. It deliberately does
NOT claim semantic correctness, scope adherence, or fidelity to frozen decisions — that
is a later reviewer phase. Validation failure happens before any artifact/journal/publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ant_orchestrator.application.ports.document_worker import MAX_PROPOSED_CONTENT_CHARS

_HEADING_PREFIX: Final = "#"


class ValidationFailure(Enum):
    """Why deterministic validation rejected the proposed document."""

    EMPTY_CONTENT = "empty_content"
    UNSUPPORTED_ENCODING = "unsupported_encoding"
    OVERSIZED = "oversized"
    MISSING_SECTION = "missing_section"
    DUPLICATE_SECTION = "duplicate_section"


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Typed validation outcome — sanitized reasons, never free-text authority."""

    ok: bool
    failures: tuple[ValidationFailure, ...]

    @classmethod
    def passed(cls) -> ValidationResult:
        return cls(True, ())

    @classmethod
    def failed(cls, *failures: ValidationFailure) -> ValidationResult:
        return cls(False, tuple(failures))


def _heading_texts(content: str) -> list[str]:
    headings: list[str] = []
    for raw in content.splitlines():
        stripped = raw.strip()
        if stripped.startswith(_HEADING_PREFIX):
            headings.append(stripped.lstrip(_HEADING_PREFIX).strip())
    return headings


class DocumentValidator:
    """Stateless, deterministic structural validator for proposed documents."""

    def validate(self, content: str, required_sections: tuple[str, ...]) -> ValidationResult:
        failures: list[ValidationFailure] = []
        if not content.strip():
            failures.append(ValidationFailure.EMPTY_CONTENT)
        if "\x00" in content:
            failures.append(ValidationFailure.UNSUPPORTED_ENCODING)
        if len(content) > MAX_PROPOSED_CONTENT_CHARS:
            failures.append(ValidationFailure.OVERSIZED)
        headings = _heading_texts(content)
        for section in required_sections:
            count = headings.count(section)
            if count == 0:
                failures.append(ValidationFailure.MISSING_SECTION)
            elif count > 1:
                failures.append(ValidationFailure.DUPLICATE_SECTION)
        if failures:
            return ValidationResult.failed(*failures)
        return ValidationResult.passed()
