"""Deterministic unified diff over authoritative before/proposed content (PHASE_5_PLAN CP4).

The diff is computed from the typed ``BeforeState`` (ABSENT → empty) and the proposed
content, labelled with the canonical repo-relative target path only — never a host
absolute path. Lines are compared on universal-newline logical lines so the diff is
deterministic across CRLF/LF. The diff text carries its own SHA-256 for tamper detection.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass

from ant_orchestrator.execution.mutation_artifacts import BeforeKind, BeforeState, sha256_text

_DEV_NULL = "/dev/null"


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Unified diff text + its digest + whether before==proposed (no-op)."""

    text: str
    digest: str
    no_change: bool


def build_document_diff(before: BeforeState, proposed: str, canonical_relpath: str) -> DiffResult:
    """Build a deterministic unified diff labelled with the canonical target path."""
    before_text = before.content or ""
    # No-op is decided on universal-newline logical lines so a pure CRLF/LF difference
    # is not treated as a change (the diff below compares the same logical lines).
    no_change = (
        before.kind is BeforeKind.PRESENT and before_text.splitlines() == proposed.splitlines()
    )
    from_label = f"a/{canonical_relpath}" if before.kind is BeforeKind.PRESENT else _DEV_NULL
    to_label = f"b/{canonical_relpath}"
    lines = difflib.unified_diff(
        before_text.splitlines(),
        proposed.splitlines(),
        fromfile=from_label,
        tofile=to_label,
        lineterm="",
    )
    text = "\n".join(lines)
    return DiffResult(text=text, digest=sha256_text(text), no_change=no_change)
