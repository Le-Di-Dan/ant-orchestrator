"""CP1 path policy tests: scope, traversal, symlink, existence, determinism.

All tests use ``tmp_path`` fixtures; no real repository paths or secrets.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.path_policy import (
    DenyReason,
    PathAccess,
    PathDecision,
    PathPolicy,
    PathScope,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _scope(tmp_path: Path, *, read: bool = True, write: bool = False) -> PathScope:
    r = (tmp_path,) if read else ()
    w = (tmp_path,) if write else ()
    return PathScope.build(read_roots=r, write_roots=w)


def _rw_scope(tmp_path: Path) -> PathScope:
    return PathScope.build(read_roots=(tmp_path,), write_roots=(tmp_path,))


def _policy(tmp_path: Path, scope: PathScope) -> PathPolicy:
    return PathPolicy(scope, workspace_root=tmp_path)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content", encoding="utf-8")
    return path


# ------------------------------------------------------------------
# §10.1 Scope basics
# ------------------------------------------------------------------


class TestScopeBasics:
    def test_allowed_read_file(self, tmp_path: Path) -> None:
        f = _touch(tmp_path / "ok.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check("ok.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW
        assert d.resolved == f

    def test_allowed_nested_read(self, tmp_path: Path) -> None:
        _touch(tmp_path / "sub" / "deep.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check("sub/deep.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW

    def test_allowed_existing_write(self, tmp_path: Path) -> None:
        _touch(tmp_path / "w.txt")
        d = _policy(tmp_path, _scope(tmp_path, read=False, write=True)).check(
            "w.txt", PathAccess.WRITE
        )
        assert d.decision is PolicyDecision.ALLOW

    def test_read_root_does_not_grant_write(self, tmp_path: Path) -> None:
        _touch(tmp_path / "r.txt")
        scope = PathScope.build(read_roots=(tmp_path,), write_roots=())
        d = _policy(tmp_path, scope).check("r.txt", PathAccess.WRITE)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.OUTSIDE_WRITE_SCOPE

    def test_write_root_does_not_grant_read(self, tmp_path: Path) -> None:
        _touch(tmp_path / "w.txt")
        scope = PathScope.build(read_roots=(), write_roots=(tmp_path,))
        d = _policy(tmp_path, scope).check("w.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.OUTSIDE_READ_SCOPE

    def test_duplicate_roots_are_deduplicated(self, tmp_path: Path) -> None:
        scope = PathScope.build(read_roots=(tmp_path, tmp_path), write_roots=())
        assert len(scope.read_roots) == 1


# ------------------------------------------------------------------
# §10.2 Outside scope
# ------------------------------------------------------------------


class TestOutsideScope:
    def test_relative_traversal(self, tmp_path: Path) -> None:
        _touch(tmp_path / "secret.txt")
        inner = tmp_path / "inner"
        inner.mkdir()
        d = _policy(inner, _scope(inner)).check("../secret.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_nested_traversal(self, tmp_path: Path) -> None:
        inner = tmp_path / "a" / "b"
        inner.mkdir(parents=True)
        _touch(tmp_path / "leak.txt")
        d = _policy(inner, _scope(inner)).check("../../leak.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_absolute_outside(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        _touch(outside / "x.txt")
        inner = tmp_path / "inner"
        inner.mkdir()
        d = _policy(inner, _scope(inner)).check(str(outside / "x.txt"), PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_prefix_collision(self, tmp_path: Path) -> None:
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        evil = tmp_path / "workspace-evil"
        evil.mkdir()
        _touch(evil / "x.txt")
        d = _policy(workspace, _scope(workspace)).check(str(evil / "x.txt"), PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_sibling_directory(self, tmp_path: Path) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        sibling = tmp_path / "sibling"
        sibling.mkdir()
        _touch(sibling / "s.txt")
        d = _policy(allowed, _scope(allowed)).check(str(sibling / "s.txt"), PathAccess.READ)
        assert d.decision is PolicyDecision.DENY


# ------------------------------------------------------------------
# §10.3 Symlink
# ------------------------------------------------------------------


_SYMLINK_SUPPORTED = hasattr(os, "symlink")


def _can_symlink(tmp_path: Path) -> bool:
    """Check whether the current platform/user can create symlinks."""
    try:
        link = tmp_path / "_symtest_link"
        target = tmp_path / "_symtest_target"
        target.write_text("t", encoding="utf-8")
        link.symlink_to(target)
        link.unlink()
        target.unlink()
        return True
    except OSError:
        return False


@pytest.fixture
def symlink_ok(tmp_path: Path) -> bool:
    return _can_symlink(tmp_path)


class TestSymlink:
    def test_internal_symlink_within_scope(self, tmp_path: Path, symlink_ok: bool) -> None:
        if not symlink_ok:
            pytest.skip("symlinks not supported on this platform/user")
        _touch(tmp_path / "real.txt")
        (tmp_path / "link.txt").symlink_to(tmp_path / "real.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check("link.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW

    def test_symlink_escapes_scope(self, tmp_path: Path, symlink_ok: bool) -> None:
        if not symlink_ok:
            pytest.skip("symlinks not supported")
        outside = tmp_path / "outside"
        outside.mkdir()
        _touch(outside / "secret.txt")
        inner = tmp_path / "inner"
        inner.mkdir()
        (inner / "escape.txt").symlink_to(outside / "secret.txt")
        d = _policy(inner, _scope(inner)).check("escape.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY
        assert d.reason in (DenyReason.SYMLINK_ESCAPE, DenyReason.OUTSIDE_READ_SCOPE)

    def test_parent_symlink_escapes_scope(self, tmp_path: Path, symlink_ok: bool) -> None:
        if not symlink_ok:
            pytest.skip("symlinks not supported")
        real_outside = tmp_path / "real_outside"
        real_outside.mkdir()
        _touch(real_outside / "data.txt")
        inner = tmp_path / "inner"
        inner.mkdir()
        (inner / "fakedir").symlink_to(real_outside)
        d = _policy(inner, _scope(inner)).check("fakedir/data.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_broken_symlink_denied(self, tmp_path: Path, symlink_ok: bool) -> None:
        if not symlink_ok:
            pytest.skip("symlinks not supported")
        (tmp_path / "broken.txt").symlink_to(tmp_path / "nonexistent_target")
        d = _policy(tmp_path, _scope(tmp_path)).check("broken.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY

    def test_write_via_symlinked_parent_outside(self, tmp_path: Path, symlink_ok: bool) -> None:
        if not symlink_ok:
            pytest.skip("symlinks not supported")
        outside = tmp_path / "out"
        outside.mkdir()
        inner = tmp_path / "inner"
        inner.mkdir()
        (inner / "link_dir").symlink_to(outside)
        scope = PathScope.build(read_roots=(), write_roots=(inner,))
        d = _policy(inner, scope).check("link_dir/new.txt", PathAccess.WRITE)
        assert d.decision is PolicyDecision.DENY


# ------------------------------------------------------------------
# §10.4 Existence and file kind
# ------------------------------------------------------------------


class TestExistenceAndKind:
    def test_missing_read_target(self, tmp_path: Path) -> None:
        d = _policy(tmp_path, _scope(tmp_path)).check("nope.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.NOT_FOUND

    def test_directory_as_read_file(self, tmp_path: Path) -> None:
        (tmp_path / "subdir").mkdir()
        d = _policy(tmp_path, _scope(tmp_path)).check("subdir", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.NOT_A_FILE

    def test_directory_as_write_file(self, tmp_path: Path) -> None:
        (tmp_path / "subdir").mkdir()
        d = _policy(tmp_path, _rw_scope(tmp_path)).check("subdir", PathAccess.WRITE)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.NOT_A_FILE

    def test_missing_write_leaf_in_allowed_parent(self, tmp_path: Path) -> None:
        scope = PathScope.build(read_roots=(), write_roots=(tmp_path,))
        d = _policy(tmp_path, scope).check("newfile.txt", PathAccess.WRITE)
        assert d.decision is PolicyDecision.ALLOW

    def test_missing_write_leaf_outside_scope(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        scope = PathScope.build(read_roots=(), write_roots=(inner,))
        d = _policy(tmp_path, scope).check("outside_new.txt", PathAccess.WRITE)
        assert d.decision is PolicyDecision.DENY


# ------------------------------------------------------------------
# §10.5 Determinism and platform safety
# ------------------------------------------------------------------


class TestDeterminism:
    def test_resolution_independent_of_cwd(self, tmp_path: Path) -> None:
        _touch(tmp_path / "stable.txt")
        p = PathPolicy(_scope(tmp_path), workspace_root=tmp_path)
        d = p.check("stable.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW

    def test_unicode_filename(self, tmp_path: Path) -> None:
        _touch(tmp_path / "résumé.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check("résumé.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW

    def test_dot_segments_within_scope(self, tmp_path: Path) -> None:
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        _touch(sub / "f.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check("a/b/./f.txt", PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW

    def test_empty_request_denied(self, tmp_path: Path) -> None:
        d = _policy(tmp_path, _scope(tmp_path)).check("", PathAccess.READ)
        assert d.decision is PolicyDecision.DENY
        assert d.reason is DenyReason.INVALID_PATH

    def test_absolute_within_scope_allowed(self, tmp_path: Path) -> None:
        f = _touch(tmp_path / "abs.txt")
        d = _policy(tmp_path, _scope(tmp_path)).check(str(f), PathAccess.READ)
        assert d.decision is PolicyDecision.ALLOW


# ------------------------------------------------------------------
# §10.6 Contract invariants
# ------------------------------------------------------------------


class TestContractInvariants:
    def test_allow_must_not_have_reason(self) -> None:
        with pytest.raises(InvariantViolation):
            PathDecision(PolicyDecision.ALLOW, DenyReason.NOT_FOUND, Path("/x"))

    def test_deny_must_have_reason(self) -> None:
        with pytest.raises(InvariantViolation):
            PathDecision(PolicyDecision.DENY, None, None)

    def test_allow_must_have_resolved(self) -> None:
        with pytest.raises(InvariantViolation):
            PathDecision(PolicyDecision.ALLOW, None, None)

    def test_empty_scope_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            PathScope.build(read_roots=(), write_roots=())
