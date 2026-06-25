"""Canonical path policy — pure scope guard for filesystem access (CP1).

Decides whether a requested path is within an allowed read or write scope by
resolving it to a canonical absolute path and comparing against canonical scope
roots. Never performs filesystem I/O beyond what ``Path.resolve`` / ``Path.exists``
need for canonicalization; never writes, deletes, or creates files.

**Fail-closed**: any resolution ambiguity, missing ancestor for write, or
unresolvable symlink results in ``DENY``.

Does not import ``execution``, ``context``, ``energy``, concrete adapters, provider
SDKs, or ``subprocess``. Depends only on ``core.domain.errors``, the audit port
enum :class:`PolicyDecision`, and stdlib ``pathlib``/``os``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation


class PathAccess(Enum):
    """The kind of filesystem access being requested."""

    READ = "read"
    WRITE = "write"


class DenyReason(Enum):
    """Why a path request was denied (typed — no free-form string)."""

    OUTSIDE_READ_SCOPE = "outside_read_scope"
    OUTSIDE_WRITE_SCOPE = "outside_write_scope"
    TRAVERSAL = "traversal"
    SYMLINK_ESCAPE = "symlink_escape"
    NOT_FOUND = "not_found"
    NOT_A_FILE = "not_a_file"
    NOT_A_DIRECTORY = "not_a_directory"
    INVALID_PATH = "invalid_path"


@dataclass(frozen=True, slots=True)
class PathScope:
    """Immutable, canonical read/write roots. Created via :meth:`build`."""

    read_roots: tuple[Path, ...]
    write_roots: tuple[Path, ...]

    def __post_init__(self) -> None:
        if not self.read_roots and not self.write_roots:
            raise InvariantViolation("PathScope requires at least one read or write root")

    @classmethod
    def build(
        cls,
        *,
        read_roots: tuple[Path, ...],
        write_roots: tuple[Path, ...],
    ) -> PathScope:
        """Resolve and deduplicate roots so all comparisons are canonical."""
        return cls(
            read_roots=_canonicalize_roots(read_roots),
            write_roots=_canonicalize_roots(write_roots),
        )


@dataclass(frozen=True, slots=True)
class PathDecision:
    """The outcome of a path policy check."""

    decision: PolicyDecision
    reason: DenyReason | None
    resolved: Path | None

    def __post_init__(self) -> None:
        if self.decision is PolicyDecision.ALLOW:
            if self.reason is not None:
                raise InvariantViolation("ALLOW must not carry a deny reason")
            if self.resolved is None:
                raise InvariantViolation("ALLOW must carry a resolved path")
        else:
            if self.reason is None:
                raise InvariantViolation("DENY must carry a reason")


class PathPolicy:
    """Stateless, deterministic path scope guard.

    Resolve ``workspace_root / requested`` to a canonical path and check
    containment against the appropriate scope roots. ``workspace_root`` is the
    injected authority for resolving relative requests — the process cwd is never
    consulted.
    """

    def __init__(self, scope: PathScope, workspace_root: Path) -> None:
        self._scope = scope
        self._ws = workspace_root.resolve()

    def check_directory(self, requested: str) -> PathDecision:
        """Check whether ``requested`` is an existing directory within read scope."""
        if not requested:
            return _deny(DenyReason.INVALID_PATH)
        try:
            raw = Path(requested)
        except (ValueError, TypeError):
            return _deny(DenyReason.INVALID_PATH)
        candidate = raw if raw.is_absolute() else self._ws / raw
        canonical = _safe_resolve(candidate)
        if canonical is None:
            return _deny(DenyReason.INVALID_PATH)
        if not canonical.exists():
            return _deny(DenyReason.NOT_FOUND)
        roots = self._scope.read_roots
        if not _is_within(canonical, roots):
            return _deny(DenyReason.OUTSIDE_READ_SCOPE)
        if _is_symlink_escaping(canonical, roots):
            return _deny(DenyReason.SYMLINK_ESCAPE)
        if not canonical.is_dir():
            return _deny(DenyReason.NOT_A_DIRECTORY)
        return _allow(canonical)

    def check(self, requested: str, access: PathAccess) -> PathDecision:
        """Return ALLOW with the canonical path, or DENY with the reason."""
        if not requested:
            return _deny(DenyReason.INVALID_PATH)

        try:
            raw = Path(requested)
        except (ValueError, TypeError):
            return _deny(DenyReason.INVALID_PATH)

        candidate = raw if raw.is_absolute() else self._ws / raw
        canonical = _safe_resolve(candidate)

        if canonical is None:
            return _deny(DenyReason.INVALID_PATH)

        roots = self._scope.read_roots if access is PathAccess.READ else self._scope.write_roots
        outside_reason = (
            DenyReason.OUTSIDE_READ_SCOPE
            if access is PathAccess.READ
            else DenyReason.OUTSIDE_WRITE_SCOPE
        )

        if access is PathAccess.READ:
            return self._check_read(canonical, roots, outside_reason)
        return self._check_write(canonical, candidate, roots, outside_reason)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _check_read(
        self,
        canonical: Path,
        roots: tuple[Path, ...],
        outside_reason: DenyReason,
    ) -> PathDecision:
        if not canonical.exists():
            return _deny(DenyReason.NOT_FOUND)
        if not _is_within(canonical, roots):
            return _deny(outside_reason)
        if _is_symlink_escaping(canonical, roots):
            return _deny(DenyReason.SYMLINK_ESCAPE)
        if canonical.is_dir():
            return _deny(DenyReason.NOT_A_FILE)
        return _allow(canonical)

    def _check_write(
        self,
        canonical: Path,
        original: Path,
        roots: tuple[Path, ...],
        outside_reason: DenyReason,
    ) -> PathDecision:
        if canonical.exists():
            if not _is_within(canonical, roots):
                return _deny(outside_reason)
            if _is_symlink_escaping(canonical, roots):
                return _deny(DenyReason.SYMLINK_ESCAPE)
            if canonical.is_dir():
                return _deny(DenyReason.NOT_A_FILE)
            return _allow(canonical)

        ancestor = _nearest_existing_ancestor(original)
        if ancestor is None:
            return _deny(DenyReason.NOT_FOUND)
        resolved_ancestor = _safe_resolve(ancestor)
        if resolved_ancestor is None:
            return _deny(DenyReason.INVALID_PATH)
        if not _is_within(resolved_ancestor, roots):
            return _deny(outside_reason)
        if _is_symlink_escaping(resolved_ancestor, roots):
            return _deny(DenyReason.SYMLINK_ESCAPE)

        projected = (
            resolved_ancestor / original.resolve().__class__(*original.parts[len(ancestor.parts) :])
            if len(original.parts) > len(ancestor.parts)
            else resolved_ancestor
        )
        if not _is_within(projected, roots):
            return _deny(outside_reason)
        return _allow(projected)


# ======================================================================
# Helpers (module-private)
# ======================================================================


def _canonicalize_roots(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        canonical = root.resolve()
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return tuple(result)


def _safe_resolve(path: Path) -> Path | None:
    try:
        return path.resolve()
    except (OSError, ValueError):
        return None


def _is_within(canonical: Path, roots: tuple[Path, ...]) -> bool:
    return any(_path_is_relative_to(canonical, root) for root in roots)


def _path_is_relative_to(child: Path, parent: Path) -> bool:
    """Component-safe containment check (avoids prefix-string collision)."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_symlink_escaping(canonical: Path, roots: tuple[Path, ...]) -> bool:
    """Walk each component; if any hop via symlink lands outside all roots, escape."""
    parts = canonical.parts
    for i in range(1, len(parts) + 1):
        prefix = Path(*parts[:i])
        try:
            if prefix.is_symlink():
                real = prefix.resolve()
                if not _is_within(real, roots):
                    return True
        except OSError:
            return True
    return False


def _nearest_existing_ancestor(path: Path) -> Path | None:
    current = path
    while True:
        if current.exists():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _allow(resolved: Path) -> PathDecision:
    return PathDecision(PolicyDecision.ALLOW, None, resolved)


def _deny(reason: DenyReason) -> PathDecision:
    return PathDecision(PolicyDecision.DENY, reason, None)
