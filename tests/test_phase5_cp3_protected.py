"""CP3 tests — protected path policy, scope composition, Windows fail-closed contract.

Covers (A) registry audit/config, (B) happy path, (C) protected documents incl.
collision/case/separator, (D) scope + traversal, (E) Windows lexical adversarial
matrix (runs on POSIX), (F) symlink resolution, (G) fail-closed errors. Protected
fixtures are temporary files — the real repository documents are never touched.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.path_policy import DenyReason, PathAccess, PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.security.protected_paths import (
    PROTECTED_POLICY_VERSION,
    ProtectedRegistry,
)

_PROTECTED_FIXTURES = (
    "docs/product/FOUNDATION.md",
    "docs/product/TECHNICAL_FOUNDATION.md",
    "docs/product/MVP_SCOPE.md",
    "ROADMAP.md",
    "docs/product/adr/ADR-0001-python-first-core.md",
)


def _make_files(ws: Path, relpaths: tuple[str, ...]) -> None:
    for rel in relpaths:
        path = ws / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")


def _policy(
    ws: Path,
    *,
    write_roots: tuple[Path, ...] | None = None,
    read_roots: tuple[Path, ...] = (),
    case_insensitive: bool = False,
    version: int = PROTECTED_POLICY_VERSION,
    registry: ProtectedRegistry | None = None,
) -> ProtectedPathPolicy:
    if write_roots is None:
        write_roots = (ws / "docs" / "handoffs",)
    for root in write_roots:
        root.mkdir(parents=True, exist_ok=True)
    scope = PathScope.build(read_roots=read_roots, write_roots=write_roots)
    return ProtectedPathPolicy(
        scope=scope,
        workspace_root=ws,
        registry=registry,
        policy_version=version,
        case_insensitive=case_insensitive,
    )


def _wide(ws: Path, **kwargs: object) -> ProtectedPathPolicy:
    """Policy whose write scope is the WHOLE workspace (covers protected files)."""
    return _policy(ws, write_roots=(ws,), **kwargs)  # type: ignore[arg-type]


# --- A. registry audit / configuration -------------------------------------


def test_default_registry_versioned_and_tier1_present() -> None:
    reg = ProtectedRegistry.default()
    assert reg.version == PROTECTED_POLICY_VERSION
    assert reg.matches("ROADMAP.md", case_insensitive=False)
    assert reg.matches("docs/product/FOUNDATION.md", case_insensitive=False)
    assert reg.matches("docs/product/adr/ADR-0009-new.md", case_insensitive=False)


def test_adr_directory_rule_not_prefix_collision() -> None:
    reg = ProtectedRegistry.default()
    assert reg.matches("docs/product/adr-copy/x.md", case_insensitive=False) is None


def test_tier2_documents_not_protected() -> None:
    reg = ProtectedRegistry.default()
    for rel in (
        "docs/product/AGENT_OPERATING_MODEL.md",
        "docs/product/DECISION_LOG.md",
        "docs/product/CONTEXT_POLICY.md",
        "CLAUDE.md",
    ):
        assert reg.matches(rel, case_insensitive=False) is None


def test_registry_rejects_invalid_rules() -> None:
    with pytest.raises(InvariantViolation):
        ProtectedRegistry.build(version=1, exact=("a.md", "a.md"), directories=())
    with pytest.raises(InvariantViolation):
        ProtectedRegistry.build(version=1, exact=("/abs.md",), directories=())
    with pytest.raises(InvariantViolation):
        ProtectedRegistry.build(version=1, exact=("../x.md",), directories=())
    with pytest.raises(InvariantViolation):
        ProtectedRegistry.build(
            version=1, exact=("docs/product/adr/ADR.md",), directories=("docs/product/adr",)
        )


def test_unsupported_policy_version_denies(tmp_path: Path) -> None:
    decision = _policy(tmp_path, version=999).check("docs/handoffs/x.md")
    assert decision.decision is PolicyDecision.DENY
    assert decision.reason is DenyReason.UNSUPPORTED_POLICY_VERSION


# --- B. happy path ---------------------------------------------------------


def test_allowed_relative_path_allows(tmp_path: Path) -> None:
    decision = _policy(tmp_path).check("docs/handoffs/HANDOFF-001.md")
    assert decision.decision is PolicyDecision.ALLOW
    assert decision.canonical_relpath == "docs/handoffs/HANDOFF-001.md"
    assert decision.protected_policy_version == PROTECTED_POLICY_VERSION
    assert decision.matched_rule_id is None


def test_nested_and_update_allow(tmp_path: Path) -> None:
    pol = _policy(tmp_path)
    nested = pol.check("docs/handoffs/sub/dir/N.md")
    assert nested.decision is PolicyDecision.ALLOW
    (tmp_path / "docs/handoffs/existing.md").write_text("x", encoding="utf-8")
    update = pol.check("docs/handoffs/existing.md")
    assert update.decision is PolicyDecision.ALLOW


# --- C. protected documents ------------------------------------------------


@pytest.mark.parametrize("rel", _PROTECTED_FIXTURES)
def test_exact_and_directory_protected_denied(tmp_path: Path, rel: str) -> None:
    _make_files(tmp_path, _PROTECTED_FIXTURES)
    decision = _wide(tmp_path).check(rel)
    assert decision.decision is PolicyDecision.DENY
    assert decision.reason is DenyReason.PROTECTED_DOCUMENT
    assert decision.matched_rule_id is not None


def test_protected_denied_without_target_existing(tmp_path: Path) -> None:
    # No fixture files created: deny happens lexically/by registry, needs no read.
    decision = _wide(tmp_path).check("ROADMAP.md")
    assert decision.reason is DenyReason.PROTECTED_DOCUMENT


def test_protected_case_insensitive_on_windows(tmp_path: Path) -> None:
    decision = _wide(tmp_path, case_insensitive=True).check("docs/product/foundation.md")
    assert decision.reason is DenyReason.PROTECTED_DOCUMENT


def test_protected_separator_and_dot_normalization(tmp_path: Path) -> None:
    assert _wide(tmp_path).check("docs\\product\\FOUNDATION.md").reason is (
        DenyReason.PROTECTED_DOCUMENT
    )
    assert _wide(tmp_path).check("./ROADMAP.md").reason is DenyReason.PROTECTED_DOCUMENT


def test_prefix_collision_not_protected(tmp_path: Path) -> None:
    backup = _wide(tmp_path).check("ROADMAP.md.bak")
    assert backup.matched_rule_id is None
    assert backup.reason is not DenyReason.PROTECTED_DOCUMENT
    adr_copy = _wide(tmp_path).check("docs/product/adr-copy/x.md")
    assert adr_copy.decision is PolicyDecision.ALLOW


# --- D. scope and traversal ------------------------------------------------


def test_traversal_and_absolute_denied(tmp_path: Path) -> None:
    pol = _policy(tmp_path)
    assert pol.check("../../etc/passwd").decision is PolicyDecision.DENY
    assert pol.check("/etc/passwd").decision is PolicyDecision.DENY


def test_outside_scope_and_prefix_collision_denied(tmp_path: Path) -> None:
    pol = _policy(tmp_path)
    assert pol.check("docs/other/x.md").reason is DenyReason.OUTSIDE_WRITE_SCOPE
    assert pol.check("docs/handoffs-copy/file.md").reason is DenyReason.OUTSIDE_WRITE_SCOPE


def test_empty_scope_denies(tmp_path: Path) -> None:
    scope = PathScope.build(read_roots=(tmp_path,), write_roots=())
    pol = ProtectedPathPolicy(
        scope=scope, workspace_root=tmp_path, policy_version=PROTECTED_POLICY_VERSION
    )
    assert pol.check("docs/handoffs/x.md").reason is DenyReason.INVALID_SCOPE


def test_mixed_separator_traversal_denied(tmp_path: Path) -> None:
    decision = _policy(tmp_path).check("docs\\handoffs\\..\\..\\ROADMAP.md")
    assert decision.decision is PolicyDecision.DENY


# --- E. Windows lexical adversarial matrix (runs on POSIX) ------------------

_UNSAFE = [
    "C:\\workspace\\file.md",
    "C:/workspace/file.md",
    "C:file.md",
    "C:docs\\file.md",
    "\\\\server\\share\\file.md",
    "//server/share/file.md",
    "\\\\?\\C:\\file.md",
    "\\\\.\\PhysicalDrive0",
    "\\\\?\\UNC\\server\\share\\file.md",
    "docs/file.md:stream",
    "docs/a:b.md",
    "ROADMAP.md.",
    "docs/file.md ",
    "docs/CON.md",
    "docs/NUL",
    "docs/COM1.md",
]


@pytest.mark.parametrize("requested", _UNSAFE)
def test_windows_lexical_forms_fail_closed(tmp_path: Path, requested: str) -> None:
    decision = _policy(tmp_path).check(requested)
    assert decision.decision is PolicyDecision.DENY
    assert decision.reason is DenyReason.UNSAFE_WINDOWS_PATH


def test_rooted_windows_path_denied(tmp_path: Path) -> None:
    # `\rooted\path` folds to an absolute POSIX path → scope denial (still fail closed).
    assert _policy(tmp_path).check("\\rooted\\path").decision is PolicyDecision.DENY


def test_case_insensitive_protected_bypass_blocked(tmp_path: Path) -> None:
    decision = _wide(tmp_path, case_insensitive=True).check("docs/product/ADR/adr-0001-x.md")
    assert decision.reason is DenyReason.PROTECTED_DOCUMENT


# --- F. symlink ------------------------------------------------------------


def _symlinks_supported(tmp_path: Path) -> bool:
    link = tmp_path / "_probe"
    try:
        link.symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        return False
    link.unlink()
    return True


def test_symlink_alias_to_protected_denied(tmp_path: Path) -> None:
    if not _symlinks_supported(tmp_path):
        pytest.skip("platform cannot create symlinks")
    _make_files(tmp_path, ("docs/product/FOUNDATION.md",))
    (tmp_path / "docs/handoffs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs/handoffs/alias.md").symlink_to(tmp_path / "docs/product/FOUNDATION.md")
    decision = _wide(tmp_path).check("docs/handoffs/alias.md")
    assert decision.reason is DenyReason.PROTECTED_DOCUMENT


def test_symlink_escaping_workspace_denied(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_text("x", encoding="utf-8")
    (ws / "docs/handoffs").mkdir(parents=True, exist_ok=True)
    if not _symlinks_supported(ws):
        pytest.skip("platform cannot create symlinks")
    (ws / "docs/handoffs/escape.md").symlink_to(outside / "secret.md")
    decision = _policy(ws).check("docs/handoffs/escape.md")
    assert decision.decision is PolicyDecision.DENY


# --- G. fail-closed / error handling ---------------------------------------


def test_unsupported_operation_denies(tmp_path: Path) -> None:
    decision = _policy(tmp_path).check("docs/handoffs/x.md", operation=PathAccess.READ)
    assert decision.reason is DenyReason.UNSUPPORTED_OPERATION


def test_empty_requested_denies(tmp_path: Path) -> None:
    assert _policy(tmp_path).check("").reason is DenyReason.INVALID_PATH


def test_decision_carries_typed_reason_no_raw_error(tmp_path: Path) -> None:
    decision = _policy(tmp_path).check("../escape.md")
    assert isinstance(decision.reason, DenyReason)
    assert decision.canonical_relpath is None  # no host-absolute path leakage on deny
