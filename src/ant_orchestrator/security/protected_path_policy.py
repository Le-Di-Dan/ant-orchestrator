"""Protected-path policy — write permission with fail-closed composition (PHASE_5_PLAN CP3).

Composes one canonicalization pipeline used by both scope and protected matching:

    raw target → separator-fold + lexical guard → PathPolicy (scope/traversal/symlink)
               → repo-relative canonical path → ProtectedRegistry → structured decision

``ProtectedPathPolicy`` is the WRITE/mutation guard CP4 calls BEFORE reading the
target or invoking a provider (PF-1). Authority (approved target, write scope,
policy version, workspace root) comes from ``ApprovedExecutionScope`` — never from a
model. Every ambiguity denies: unsupported version, unsafe lexical form, scope
failure, un-canonicalizable target, or a protected match all fail closed. A base
allowed scope can NEVER override a protected rule.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.path_policy import DenyReason, PathAccess, PathPolicy, PathScope
from ant_orchestrator.security.protected_paths import ProtectedRegistry
from ant_orchestrator.security.windows_path import is_lexically_unsafe, normalize_separators


@dataclass(frozen=True, slots=True)
class ProtectedPathDecision:
    """Structured, sanitized permission decision (no host-absolute path, no raw error)."""

    decision: PolicyDecision
    reason: DenyReason | None
    operation: PathAccess
    requested: str
    protected_policy_version: int
    canonical_relpath: str | None = None
    matched_rule_id: str | None = None

    def __post_init__(self) -> None:
        if self.decision is PolicyDecision.ALLOW:
            if self.reason is not None:
                raise InvariantViolation("ALLOW must not carry a deny reason")
            if self.canonical_relpath is None:
                raise InvariantViolation("ALLOW must carry a canonical repo-relative path")
            if self.matched_rule_id is not None:
                raise InvariantViolation("ALLOW must not carry a protected rule id")
        elif self.reason is None:
            raise InvariantViolation("DENY must carry a reason")


class ProtectedPathPolicy:
    """Write-permission guard layering protected rules over the base scope policy."""

    def __init__(
        self,
        *,
        scope: PathScope,
        workspace_root: Path,
        registry: ProtectedRegistry | None = None,
        policy_version: int,
        case_insensitive: bool | None = None,
    ) -> None:
        self._scope = scope
        self._ws = workspace_root.resolve()
        self._path_policy = PathPolicy(scope, workspace_root)
        self._registry = registry if registry is not None else ProtectedRegistry.default()
        self._policy_version = policy_version
        self._ci = case_insensitive if case_insensitive is not None else os.name == "nt"

    def check(
        self, requested: str, operation: PathAccess = PathAccess.WRITE
    ) -> ProtectedPathDecision:
        """Return a structured ALLOW (with canonical repo-relative path) or DENY."""
        if self._policy_version != self._registry.version:
            return self._deny(DenyReason.UNSUPPORTED_POLICY_VERSION, requested, operation)
        if operation is not PathAccess.WRITE:
            return self._deny(DenyReason.UNSUPPORTED_OPERATION, requested, operation)
        if not self._scope.write_roots:
            return self._deny(DenyReason.INVALID_SCOPE, requested, operation)
        if not requested:
            return self._deny(DenyReason.INVALID_PATH, requested, operation)

        normalized = normalize_separators(requested)
        if is_lexically_unsafe(normalized):
            return self._deny(DenyReason.UNSAFE_WINDOWS_PATH, requested, operation)

        base = self._path_policy.check(normalized, operation)
        if base.decision is not PolicyDecision.ALLOW or base.resolved is None:
            return self._deny(base.reason or DenyReason.INVALID_PATH, requested, operation)

        relpath = self._repo_relative(base.resolved)
        if relpath is None:
            return self._deny(DenyReason.PATH_CANONICALIZATION_FAILED, requested, operation)

        rule_id = self._registry.matches(relpath, case_insensitive=self._ci)
        if rule_id is not None:
            return self._deny(
                DenyReason.PROTECTED_DOCUMENT,
                requested,
                operation,
                relpath=relpath,
                rule_id=rule_id,
            )
        return ProtectedPathDecision(
            decision=PolicyDecision.ALLOW,
            reason=None,
            operation=operation,
            requested=requested,
            protected_policy_version=self._policy_version,
            canonical_relpath=relpath,
        )

    def _repo_relative(self, resolved: Path) -> str | None:
        try:
            return resolved.relative_to(self._ws).as_posix()
        except ValueError:
            return None

    def _deny(
        self,
        reason: DenyReason,
        requested: str,
        operation: PathAccess,
        *,
        relpath: str | None = None,
        rule_id: str | None = None,
    ) -> ProtectedPathDecision:
        return ProtectedPathDecision(
            decision=PolicyDecision.DENY,
            reason=reason,
            operation=operation,
            requested=requested,
            protected_policy_version=self._policy_version,
            canonical_relpath=relpath,
            matched_rule_id=rule_id,
        )
