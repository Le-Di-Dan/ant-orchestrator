"""Isolation contract abstraction for the Test Ant (PHASE_6_PLAN CP1, §D.4/§E).

The application/worker/graph layers see only this port; they never learn that the MVP
backend is Docker (ADR-0007). No ``docker run`` argv, host shell string or host absolute
path may appear on any contract here — only logical references and typed policy.

A concrete backend (CP2, ``adapters/``) implements :class:`TestIsolationPort`. Backend
unavailability is representable and fail-closed: capability defaults to UNAVAILABLE.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import TestReasonCode

_REF_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]*$")
MAX_ENV_ALLOWLIST = 32


def _validate_logical_ref(value: str, field: str) -> None:
    """A logical reference is a compact token, never a shell/argv string."""
    if not value:
        raise InvariantViolation(f"{field} must be non-empty")
    if " " in value or "\t" in value or "\n" in value:
        raise InvariantViolation(f"{field} must not contain whitespace (no shell string)")
    if value.startswith("--") or value.startswith(("/", "\\")):
        raise InvariantViolation(f"{field} must not be a CLI flag or host absolute path")
    if not _REF_RE.fullmatch(value):
        raise InvariantViolation(f"{field} is not a safe logical reference")


class IsolationStatus(_StrEnum):
    """Whether an isolation backend is usable right now (fail-closed default)."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class NetworkPolicy(_StrEnum):
    """Network exposure for an isolated test run. Disabled by default (MVP)."""

    DISABLED = "disabled"
    ENABLED = "enabled"


class EnvironmentPolicy(_StrEnum):
    """How the environment is presented inside the isolation boundary.

    ``SANITIZED_MINIMAL`` passes no host environment and no secrets; an optional
    name-only allowlist may admit specific variable *names* (never values).
    """

    SANITIZED_MINIMAL = "sanitized_minimal"


class IsolatedRunStatus(_StrEnum):
    """Terminal status of one isolated run, from the boundary's point of view."""

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    LAUNCH_FAILED = "launch_failed"
    ISOLATION_UNAVAILABLE = "isolation_unavailable"
    ISOLATION_SETUP_FAILED = "isolation_setup_failed"


class BackendReason(_StrEnum):
    """Stable, allowlisted reason for a failed launch/setup (PHASE_6_PLAN CP4, §2.2).

    Typed signal surfaced from the isolation backend to the classifier. Only allowlisted
    values may influence transience/disposition — no raw exception or string parsing.
    Moved here from workers/test/classifier.py (CP4 gap: IsolatedExecutionResult needs it).
    """

    EXECUTABLE_MISSING = "executable_missing"
    PERMISSION_DENIED = "permission_denied"
    ADAPTER_CONFIG_INVALID = "adapter_config_invalid"
    RESOURCE_TEMPORARILY_UNAVAILABLE = "resource_temporarily_unavailable"
    PROCESS_INTERRUPTION = "process_interruption"
    ISOLATION_VIOLATION = "isolation_violation"


@dataclass(frozen=True, slots=True)
class IsolationCapability:
    """Result of a backend availability preflight (fail-closed).

    When ``status`` is UNAVAILABLE a ``reason_code`` explains why, so the worker can
    classify ``EXECUTION_ISOLATION_UNAVAILABLE`` and fail closed (no host fallback).
    """

    status: IsolationStatus
    backend_ref: str | None = None
    reason_code: TestReasonCode | None = None

    def __post_init__(self) -> None:
        if self.backend_ref is not None:
            _validate_logical_ref(self.backend_ref, "IsolationCapability.backend_ref")
        if self.status is IsolationStatus.UNAVAILABLE and self.reason_code is None:
            raise InvariantViolation("UNAVAILABLE capability requires a reason_code")

    @property
    def is_available(self) -> bool:
        return self.status is IsolationStatus.AVAILABLE

    def to_state_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "backend_ref": self.backend_ref,
            "reason_code": self.reason_code.value if self.reason_code else None,
        }


@dataclass(frozen=True, slots=True)
class IsolatedExecutionSpec:
    """Immutable, backend-neutral spec for one isolated test run (PHASE_6_PLAN §D.4).

    Carries only logical references and typed policy — never a ``docker run`` argv, a host
    shell string, or a host absolute path. ``command_profile_key`` names a validated
    profile (resolved to argv inside the backend); ``image_ref`` is a pinned logical
    image/backend reference (e.g. a digest), not a command.
    """

    snapshot_ref: str
    runtime_output_ref: str
    command_profile_key: str
    timeout_ms: int
    max_processes: int
    network_policy: NetworkPolicy = NetworkPolicy.DISABLED
    environment_policy: EnvironmentPolicy = EnvironmentPolicy.SANITIZED_MINIMAL
    env_name_allowlist: tuple[str, ...] = ()
    non_root: bool = True
    read_only_root: bool = True
    image_ref: str | None = None

    def __post_init__(self) -> None:
        _validate_logical_ref(self.snapshot_ref, "IsolatedExecutionSpec.snapshot_ref")
        _validate_logical_ref(self.runtime_output_ref, "IsolatedExecutionSpec.runtime_output_ref")
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", self.command_profile_key):
            raise InvariantViolation("command_profile_key must be a simple identifier")
        if self.timeout_ms <= 0:
            raise InvariantViolation("IsolatedExecutionSpec.timeout_ms must be > 0")
        if self.max_processes <= 0:
            raise InvariantViolation("IsolatedExecutionSpec.max_processes must be > 0")
        if self.image_ref is not None:
            _validate_logical_ref(self.image_ref, "IsolatedExecutionSpec.image_ref")
        if len(self.env_name_allowlist) > MAX_ENV_ALLOWLIST:
            raise InvariantViolation("IsolatedExecutionSpec.env_name_allowlist exceeds the bound")
        for name in self.env_name_allowlist:
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                raise InvariantViolation("env_name_allowlist entries must be NAME-only identifiers")


@dataclass(frozen=True, slots=True)
class IsolatedExecutionResult:
    """Bounded, JSON-safe result of one isolated run (no raw output/exception/path).

    ``backend_reason`` (CP4) is the typed, allowlisted signal the backend may surface for
    a failed launch/setup. It drives the classifier's transience decision without any
    string parsing — only values in :class:`BackendReason` are valid.
    """

    status: IsolatedRunStatus
    exit_code: int | None = None
    duration_ms: int = 0
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    backend_reason: BackendReason | None = None  # CP4: typed refinement (additive)

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise InvariantViolation("IsolatedExecutionResult.duration_ms must be >= 0")

    def to_state_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "evidence_refs": list(self.evidence_refs),
        }


@runtime_checkable
class TestIsolationPort(Protocol):
    """Backend-neutral isolation boundary for read-only test execution.

    A concrete backend (Docker, CP2) implements this. The worker calls
    :meth:`capability` first and fails closed if the backend is unavailable.
    """

    __test__: ClassVar[bool] = False  # domain term; not a pytest test class

    def capability(self) -> IsolationCapability:
        """Preflight: is the isolation backend usable right now? Fail-closed."""
        ...

    def run(self, spec: IsolatedExecutionSpec) -> IsolatedExecutionResult:
        """Execute the spec inside the enforced boundary and return a bounded result."""
        ...
