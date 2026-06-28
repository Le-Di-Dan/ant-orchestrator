"""Trusted test-command profiles and resolver (PHASE_6_PLAN CP2, §3.1).

The worker never supplies argv, a shell string, an environment or an executable: it
supplies a trusted ``command_key``. A :class:`TestCommandProfile` maps that key to an
immutable, versioned inner argv. The acceptance profile runs the WHOLE approved snapshot
(``python -m pytest``) and never narrows the suite with ``-k`` / ``-m`` / ``--ignore`` —
narrowing is structurally impossible because only validated, in-scope relative-path
targets may be appended, never options.

Pure policy: no process execution, no filesystem I/O, no subprocess. The resolved inner
argv is additionally validated against :class:`CommandPolicy` before any execution.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ant_orchestrator.core.domain.enums import PolicyDecision, _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.errors import AntError
from ant_orchestrator.security.command_policy import CommandPolicy
from ant_orchestrator.security.windows_path import is_lexically_unsafe, normalize_separators

_COMMAND_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
ACCEPTANCE_COMMAND_KEY = "pytest.acceptance"


class TestCommandError(AntError):
    """Base class for trusted-command-profile failures (fail-closed)."""

    __test__ = False  # domain term; not a pytest test class


class UnknownCommandKey(TestCommandError):
    """A command key has no registered profile."""


class TestCommandPolicyDenied(TestCommandError):
    """A resolved inner argv was denied by the command policy."""

    __test__ = False  # domain term; not a pytest test class


class TestTargetRejected(TestCommandError):
    """A requested target is not a safe, in-scope relative path."""

    __test__ = False  # domain term; not a pytest test class


class TestCommandKind(_StrEnum):
    """Acceptance (pass/fail authority) vs diagnostic (never pass/fail evidence)."""

    __test__ = False  # domain term; not a pytest test class

    ACCEPTANCE = "acceptance"
    DIAGNOSTIC = "diagnostic"


def _validate_target(target: str) -> str:
    """Return a normalized, in-scope relative path or raise :class:`TestTargetRejected`."""
    if not target:
        raise TestTargetRejected("empty target")
    if target.startswith("-"):
        raise TestTargetRejected("option-like target is not allowed")
    normalized = normalize_separators(target)
    if normalized.startswith("/"):
        raise TestTargetRejected("absolute target is not allowed")
    if is_lexically_unsafe(normalized):
        raise TestTargetRejected("lexically unsafe target")
    if ".." in normalized.split("/"):
        raise TestTargetRejected("path traversal is not allowed")
    return normalized


@dataclass(frozen=True, slots=True)
class TestCommandProfile:
    """Immutable, versioned mapping from a command key to inner argv (no shell/env)."""

    __test__ = False  # domain term; not a pytest test class

    command_key: str
    kind: TestCommandKind
    base_argv: tuple[str, ...]
    version: int
    allows_targets: bool = False

    def __post_init__(self) -> None:
        if not _COMMAND_KEY_RE.fullmatch(self.command_key):
            raise InvariantViolation("TestCommandProfile.command_key must be a simple identifier")
        if not self.base_argv or not self.base_argv[0].strip():
            raise InvariantViolation("TestCommandProfile.base_argv must start with an executable")
        if self.version < 1:
            raise InvariantViolation("TestCommandProfile.version must be >= 1")

    @property
    def is_acceptance(self) -> bool:
        return self.kind is TestCommandKind.ACCEPTANCE

    def resolve(self, targets: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Return the inner argv, appending only validated in-scope path targets."""
        if targets and not self.allows_targets:
            raise TestTargetRejected(f"profile {self.command_key} does not accept targets")
        validated = tuple(_validate_target(t) for t in targets)
        return (*self.base_argv, *validated)


class TestCommandRegistry:
    """Immutable lookup of trusted profiles by key (fail-closed on unknown key)."""

    __test__ = False  # domain term; not a pytest test class

    def __init__(self, profiles: tuple[TestCommandProfile, ...]) -> None:
        by_key: dict[str, TestCommandProfile] = {}
        for profile in profiles:
            if profile.command_key in by_key:
                raise InvariantViolation(f"duplicate command_key {profile.command_key}")
            by_key[profile.command_key] = profile
        self._by_key = by_key

    def get(self, command_key: str) -> TestCommandProfile:
        profile = self._by_key.get(command_key)
        if profile is None:
            raise UnknownCommandKey(f"no profile for command_key {command_key!r}")
        return profile

    def keys(self) -> tuple[str, ...]:
        return tuple(sorted(self._by_key))


class TestCommandResolver:
    """Resolve a command key (+ optional targets) to a policy-approved inner argv."""

    __test__ = False  # domain term; not a pytest test class

    def __init__(self, registry: TestCommandRegistry, command_policy: CommandPolicy) -> None:
        self._registry = registry
        self._policy = command_policy

    def resolve(self, command_key: str, targets: tuple[str, ...] = ()) -> tuple[str, ...]:
        """Return the validated inner argv or raise a typed, fail-closed error."""
        profile = self._registry.get(command_key)
        inner_argv = profile.resolve(targets)
        decision = self._policy.check(inner_argv)
        if decision.decision is PolicyDecision.DENY:
            raise TestCommandPolicyDenied(f"inner argv denied for {command_key}")
        return inner_argv


def default_test_command_registry() -> TestCommandRegistry:
    """Production registry: a single acceptance profile running the full snapshot suite."""
    return TestCommandRegistry(
        (
            TestCommandProfile(
                command_key=ACCEPTANCE_COMMAND_KEY,
                kind=TestCommandKind.ACCEPTANCE,
                base_argv=("python", "-m", "pytest"),
                version=1,
                allows_targets=True,
            ),
        )
    )
