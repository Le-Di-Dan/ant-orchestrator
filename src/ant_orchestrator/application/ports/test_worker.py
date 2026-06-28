"""Test Ant intent and read-only authority contracts (PHASE_6_PLAN CP1, §E).

Mirrors the intent-vs-authority split of ``execution_scope.py`` but for a strictly
read-only worker:

* :class:`TestTask` is pure *intent* — which allowed command to run against which
  in-scope targets. It carries no free-form argv, no writable paths, no shell string and
  no filesystem/Docker authority.
* :class:`TestExecutionScope` is the *authority* the worker consumes. It is read-only by
  construction: there is no write scope, no ``DocumentOperation``, no mutator, no Git
  permission, no environment dictionary, no argv and no host absolute path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ant_orchestrator.core.domain.errors import InvariantViolation

# A command key selects a pre-registered, validated command profile (CP2). It is an
# identifier, never an argv or shell fragment.
_COMMAND_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_SHELL_METACHARS = frozenset(";|&$><`\n\r\t")

MAX_TEST_TARGETS = 64
MAX_READ_SCOPE_ENTRIES = 512


def _reject_unsafe_relative_path(value: str, field: str) -> None:
    """Reject absolute paths, drive letters, traversal and shell metacharacters."""
    if not value:
        raise InvariantViolation(f"{field} entry must be non-empty")
    if value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":"):
        raise InvariantViolation(f"{field} must be a workspace-relative path, not absolute")
    if ".." in value.split("/") or ".." in value.split("\\"):
        raise InvariantViolation(f"{field} must not contain path traversal")
    if any(ch in _SHELL_METACHARS for ch in value):
        raise InvariantViolation(f"{field} must not contain shell metacharacters")


def _validate_command_key(value: str) -> None:
    if not _COMMAND_KEY_RE.fullmatch(value):
        raise InvariantViolation("command_key must be a simple identifier, not an argv")


@dataclass(frozen=True, slots=True)
class TestTask:
    """Immutable, sanitized intent: run command ``command_key`` over ``targets``.

    No raw argv, no writable paths, no Docker command, no shell string. ``targets`` are
    canonical, workspace-relative path references the command may read.
    """

    __test__ = False  # domain term; not a pytest test class

    task_ref: str
    logical_action_id: str
    command_key: str
    targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("task_ref", "logical_action_id"):
            if not getattr(self, name):
                raise InvariantViolation(f"TestTask.{name} must be non-empty")
        _validate_command_key(self.command_key)
        if len(self.targets) > MAX_TEST_TARGETS:
            raise InvariantViolation("TestTask.targets exceeds the bound")
        for target in self.targets:
            _reject_unsafe_relative_path(target, "TestTask.targets")


@dataclass(frozen=True, slots=True)
class TestExecutionScope:
    """Immutable read-only authority the Test Ant consumes (PHASE_6_PLAN §E/§J).

    Read-only by construction: a write scope, document operation, mutator, Git
    permission, environment dict, argv or host absolute path simply do not exist on this
    contract. The worker reads only ``canonical_read_scope`` and runs only the validated
    profile named by ``command_profile_key`` inside the isolation backend named by
    ``isolation_ref``.
    """

    __test__ = False  # domain term; not a pytest test class

    attempt_id: str
    run_id: str
    logical_action_id: str
    canonical_read_scope: tuple[str, ...]
    command_profile_key: str
    idempotency_key: str
    isolation_ref: str | None = None
    # CP4 context binding (additive, backward-compatible):
    # Approved workflow context manifest digest (from GraphState) — empty means no binding.
    context_manifest_digest: str = ""
    # Digest of canonical_read_scope computed by DurableTestExecution; stable per strategy.
    read_scope_digest: str = ""

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "run_id",
            "logical_action_id",
            "idempotency_key",
        ):
            if not getattr(self, name):
                raise InvariantViolation(f"TestExecutionScope.{name} must be non-empty")
        _validate_command_key(self.command_profile_key)
        if not self.canonical_read_scope:
            raise InvariantViolation("TestExecutionScope.canonical_read_scope must be non-empty")
        if len(self.canonical_read_scope) > MAX_READ_SCOPE_ENTRIES:
            raise InvariantViolation("TestExecutionScope.canonical_read_scope exceeds the bound")
        for entry in self.canonical_read_scope:
            _reject_unsafe_relative_path(entry, "TestExecutionScope.canonical_read_scope")
        if self.isolation_ref is not None and not self.isolation_ref:
            raise InvariantViolation("TestExecutionScope.isolation_ref must be non-empty if set")
