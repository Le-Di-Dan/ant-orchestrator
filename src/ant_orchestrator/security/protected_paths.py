"""Protected-document registry — audit-based, versioned, code (not DB) (PHASE_5_PLAN CP3).

Tier 1 (auto-deny) is derived from a real repository audit, NOT from fuzzy name
matching: the three Frozen-Draft product docs, the governance ROADMAP, and the ADR
directory (every ADR is ``Trạng thái: Accepted`` → a single directory rule is the
smallest safe rule). Tier 2 governance/Draft docs are deliberately ABSENT — adding
one is a policy-versioned governance change, never an implicit substring match.

Matching is path-component based (never string ``startswith``) so prefix collisions
(``ROADMAP.md.bak``, ``docs/product/adr-copy/``) never false-positive. Case folding
is decided by the caller (Windows = case-insensitive, POSIX = case-sensitive).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from ant_orchestrator.core.domain.errors import InvariantViolation

PROTECTED_POLICY_VERSION: Final = 1

# Tier 1 — confirmed protected (repo audit). Repo-relative POSIX paths.
_TIER1_EXACT: Final = (
    "docs/product/FOUNDATION.md",
    "docs/product/TECHNICAL_FOUNDATION.md",
    "docs/product/MVP_SCOPE.md",
    "ROADMAP.md",
)
_TIER1_DIRECTORIES: Final = ("docs/product/adr",)


class ProtectedRuleKind(Enum):
    """Whether a rule matches one exact file or every file under a directory."""

    EXACT = "exact"
    DIRECTORY = "directory"


@dataclass(frozen=True, slots=True)
class ProtectedRule:
    """One validated protected rule with a stable id and component tuple."""

    rule_id: str
    kind: ProtectedRuleKind
    components: tuple[str, ...]
    folded: tuple[str, ...]


def _validate_components(path: str) -> tuple[str, ...]:
    if not path or path.startswith("/") or ":" in path or "\\" in path:
        raise InvariantViolation(f"protected rule path is not workspace-relative: {path!r}")
    components = tuple(path.split("/"))
    if any(c in ("", ".", "..") for c in components):
        raise InvariantViolation(f"protected rule path has empty/traversal segment: {path!r}")
    return components


def _fold(components: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(c.lower() for c in components)


def _is_prefix(prefix: tuple[str, ...], components: tuple[str, ...]) -> bool:
    return len(components) > len(prefix) and components[: len(prefix)] == prefix


@dataclass(frozen=True, slots=True)
class ProtectedRegistry:
    """Immutable, versioned set of protected rules with component-based matching."""

    version: int
    rules: tuple[ProtectedRule, ...]

    @classmethod
    def default(cls) -> ProtectedRegistry:
        """Build the audited Tier 1 registry (Frozen Drafts + ROADMAP + ADR dir)."""
        return cls.build(
            version=PROTECTED_POLICY_VERSION,
            exact=_TIER1_EXACT,
            directories=_TIER1_DIRECTORIES,
        )

    @classmethod
    def build(
        cls, *, version: int, exact: tuple[str, ...], directories: tuple[str, ...]
    ) -> ProtectedRegistry:
        """Validate and assemble rules; reject absolute/traversal/duplicate/conflicting."""
        rules: list[ProtectedRule] = []
        seen: set[tuple[str, ...]] = set()
        dir_rules: list[tuple[str, ...]] = [_validate_components(d) for d in directories]
        for path in directories:
            comps = _validate_components(path)
            if comps in seen:
                raise InvariantViolation(f"duplicate protected directory rule: {path!r}")
            seen.add(comps)
            rules.append(
                ProtectedRule(f"dir:{path}", ProtectedRuleKind.DIRECTORY, comps, _fold(comps))
            )
        for path in exact:
            comps = _validate_components(path)
            if comps in seen:
                raise InvariantViolation(f"duplicate protected exact rule: {path!r}")
            if any(_is_prefix(d, comps) for d in dir_rules):
                raise InvariantViolation(f"exact rule {path!r} is already covered by a directory")
            seen.add(comps)
            rules.append(
                ProtectedRule(f"exact:{path}", ProtectedRuleKind.EXACT, comps, _fold(comps))
            )
        return cls(version=version, rules=tuple(rules))

    def matches(self, repo_relative: str, *, case_insensitive: bool) -> str | None:
        """Return the matched rule id, or None. Component-based, never prefix-string."""
        components = tuple(c for c in repo_relative.split("/") if c)
        if case_insensitive:
            components = _fold(components)
        for rule in self.rules:
            target = rule.folded if case_insensitive else rule.components
            if rule.kind is ProtectedRuleKind.EXACT and components == target:
                return rule.rule_id
            if rule.kind is ProtectedRuleKind.DIRECTORY and _is_prefix(target, components):
                return rule.rule_id
        return None
