"""Deterministic secret redaction over text (CP0).

Pure: no filesystem/network/logging side effects, no adapter or provider import.
Applies a sequence of :class:`SecretRule` detectors, replacing each matched secret
with a fixed marker. The result carries only the marker'd text and per-pattern
counts — never the matched secret value — so it is safe to persist, log or embed
in audit metadata. Redaction must run before any persistence/truncation
(CONTEXT/ENERGY/EXECUTION evidence).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.redaction.patterns import (
    DEFAULT_SECRET_RULES,
    SecretPattern,
    SecretRule,
)

REDACTION_REPLACEMENT_MARKER: Final = "[REDACTED]"


@dataclass(frozen=True, slots=True)
class RedactionMark:
    """A count of redactions for a single secret pattern (no secret value)."""

    pattern: SecretPattern
    count: int

    def __post_init__(self) -> None:
        if self.count < 1:
            raise InvariantViolation("RedactionMark.count must be >= 1")


@dataclass(frozen=True, slots=True)
class RedactionResult:
    """Redacted text plus the per-pattern marks describing what was removed."""

    text: str
    marks: tuple[RedactionMark, ...]


class Redactor:
    """Applies secret detectors to text, returning sanitized text + marks."""

    def __init__(
        self,
        rules: tuple[SecretRule, ...] = DEFAULT_SECRET_RULES,
        *,
        marker: str = REDACTION_REPLACEMENT_MARKER,
    ) -> None:
        if not marker:
            raise InvariantViolation("Redactor marker must be non-empty")
        self._rules = rules
        self._marker = marker

    def redact(self, text: str) -> RedactionResult:
        """Return ``text`` with every detected secret replaced by the marker."""
        current = text
        marks: list[RedactionMark] = []
        for rule in self._rules:
            current, count = self._apply(rule, current)
            if count:
                marks.append(RedactionMark(rule.pattern, count))
        return RedactionResult(current, tuple(marks))

    def _apply(self, rule: SecretRule, text: str) -> tuple[str, int]:
        if rule.redact_group == 0:
            return rule.regex.subn(self._marker, text)

        count = 0

        def _replace(match: re.Match[str]) -> str:
            nonlocal count
            count += 1
            whole = match.group(0)
            start = match.start(rule.redact_group) - match.start(0)
            end = match.end(rule.redact_group) - match.start(0)
            return whole[:start] + self._marker + whole[end:]

        return rule.regex.sub(_replace, text), count
