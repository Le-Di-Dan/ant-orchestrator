"""CP2 — trusted test-command profiles and resolver (no Docker)."""

from __future__ import annotations

import pytest

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.test_command_profile import (
    ACCEPTANCE_COMMAND_KEY,
    TestCommandKind,
    TestCommandPolicyDenied,
    TestCommandProfile,
    TestCommandRegistry,
    TestCommandResolver,
    TestTargetRejected,
    UnknownCommandKey,
    default_test_command_registry,
)

_PYTEST_POLICY = CommandPolicy(
    (CommandRule("python", allowed_arg_prefixes=(("-m", "pytest"),), allow_trailing_args=True),)
)


def _acceptance() -> TestCommandProfile:
    return default_test_command_registry().get(ACCEPTANCE_COMMAND_KEY)


def test_default_acceptance_resolves_to_exact_argv() -> None:
    assert _acceptance().resolve() == ("python", "-m", "pytest")


def test_acceptance_appends_only_validated_targets() -> None:
    argv = _acceptance().resolve(("tests/unit", "src/pkg/mod.py"))
    assert argv == ("python", "-m", "pytest", "tests/unit", "src/pkg/mod.py")


def test_unknown_command_key_fails_closed() -> None:
    with pytest.raises(UnknownCommandKey):
        default_test_command_registry().get("does.not.exist")


def test_profile_without_targets_rejects_targets() -> None:
    profile = TestCommandProfile("probe.x", TestCommandKind.DIAGNOSTIC, ("python", "x.py"), 1)
    with pytest.raises(TestTargetRejected):
        profile.resolve(("anything",))


@pytest.mark.parametrize(
    "bad", ["-k", "--ignore", "-p", "/etc/passwd", "../escape", "a:b", "CON", "sub/../x"]
)
def test_targets_reject_options_absolute_traversal_and_unsafe(bad: str) -> None:
    with pytest.raises(TestTargetRejected):
        _acceptance().resolve((bad,))


def test_resolver_approves_acceptance_inner_argv() -> None:
    resolver = TestCommandResolver(default_test_command_registry(), _PYTEST_POLICY)
    assert resolver.resolve(ACCEPTANCE_COMMAND_KEY, ("tests",)) == (
        "python",
        "-m",
        "pytest",
        "tests",
    )


def test_resolver_denies_inner_argv_outside_policy() -> None:
    # A diagnostic profile resolving to a non-pytest python invocation is denied by the
    # strict acceptance policy (the inner argv must still pass CommandPolicy).
    registry = TestCommandRegistry(
        (TestCommandProfile("probe.x", TestCommandKind.DIAGNOSTIC, ("python", "probe.py"), 1),)
    )
    resolver = TestCommandResolver(registry, _PYTEST_POLICY)
    with pytest.raises(TestCommandPolicyDenied):
        resolver.resolve("probe.x")


def test_registry_rejects_duplicate_keys() -> None:
    profile = TestCommandProfile(ACCEPTANCE_COMMAND_KEY, TestCommandKind.ACCEPTANCE, ("python",), 1)
    with pytest.raises(InvariantViolation):
        TestCommandRegistry((profile, profile))


def test_acceptance_profile_is_acceptance_kind() -> None:
    assert _acceptance().is_acceptance
    diagnostic = TestCommandProfile("probe.x", TestCommandKind.DIAGNOSTIC, ("python", "x.py"), 1)
    assert not diagnostic.is_acceptance


def test_profile_validates_key_and_version() -> None:
    with pytest.raises(InvariantViolation):
        TestCommandProfile("Bad Key", TestCommandKind.ACCEPTANCE, ("python",), 1)
    with pytest.raises(InvariantViolation):
        TestCommandProfile("ok.key", TestCommandKind.ACCEPTANCE, ("python",), 0)
    with pytest.raises(InvariantViolation):
        TestCommandProfile("ok.key", TestCommandKind.ACCEPTANCE, (), 1)
