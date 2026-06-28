"""Snapshot provisioning + bounded-output ports for the Test Ant (PHASE_6_PLAN CP3).

The :class:`TestAnt` never imports the Docker backend or the snapshot builder concretely.
It depends only on these small, typed ports:

* :class:`TestSnapshotProvisioner` builds + verifies an exact-byte snapshot (CP2
  ``ExecutionSnapshotBuilder``) and yields a *logical* snapshot reference plus the runtime
  output reference the isolation backend will use — never a host absolute path. It also
  owns cleanup (CP2 ``cleanup_snapshot``).
* :class:`TestOutputReader` optionally returns the already bounded/redacted run output so a
  pure parser can extract counts. It is optional: when absent, counts are ``unavailable``
  and the test result is derived from exit/process facts alone.

No I/O, no subprocess and no Docker imports live here — only the contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol, runtime_checkable

from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation


def _validate_ref(value: str, field_name: str) -> None:
    """A logical reference is a compact token, never a host path or shell string."""
    if not value:
        raise InvariantViolation(f"{field_name} must be non-empty")
    if value.startswith(("/", "\\")) or (len(value) >= 2 and value[1] == ":"):
        raise InvariantViolation(f"{field_name} must not be a host absolute path")
    if any(ch in value for ch in " \t\n\r"):
        raise InvariantViolation(f"{field_name} must not contain whitespace")


class SnapshotProvisionStatus(_StrEnum):
    """Outcome of building + verifying the exact-byte execution snapshot."""

    BUILT_VERIFIED = "built_verified"
    INTEGRITY_MISMATCH = "integrity_mismatch"
    SETUP_FAILED = "setup_failed"


class CleanupStatus(_StrEnum):
    """Outcome of releasing the snapshot/runtime artifacts (security-aware)."""

    CLEAN = "clean"
    FAILED = "failed"
    FAILED_SECURITY_IMPACT = "failed_security_impact"


@dataclass(frozen=True, slots=True)
class ProvisionedSnapshot:
    """A built (and verified) snapshot, referenced only by logical, host-free tokens."""

    status: SnapshotProvisionStatus
    snapshot_ref: str | None = None
    runtime_output_ref: str | None = None
    manifest_digest: str | None = None
    file_count: int = 0
    total_bytes: int = 0
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.status is SnapshotProvisionStatus.BUILT_VERIFIED:
            if not self.snapshot_ref or not self.runtime_output_ref or not self.manifest_digest:
                raise InvariantViolation("a verified snapshot requires refs and a manifest digest")
        if self.snapshot_ref is not None:
            _validate_ref(self.snapshot_ref, "ProvisionedSnapshot.snapshot_ref")
        if self.runtime_output_ref is not None:
            _validate_ref(self.runtime_output_ref, "ProvisionedSnapshot.runtime_output_ref")
        if self.file_count < 0 or self.total_bytes < 0:
            raise InvariantViolation("ProvisionedSnapshot counters must be >= 0")

    @property
    def is_verified(self) -> bool:
        return self.status is SnapshotProvisionStatus.BUILT_VERIFIED


@dataclass(frozen=True, slots=True)
class CleanupOutcome:
    """Bounded result of snapshot/runtime cleanup (no host path)."""

    status: CleanupStatus
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_clean(self) -> bool:
        return self.status is CleanupStatus.CLEAN

    @property
    def has_security_impact(self) -> bool:
        return self.status is CleanupStatus.FAILED_SECURITY_IMPACT


@dataclass(frozen=True, slots=True)
class BoundedRunOutput:
    """Already bounded + redacted run output for a pure counts parser (no raw bytes)."""

    text: str
    truncated: bool = False
    original_bytes: int = 0
    redaction_applied: bool = False

    def __post_init__(self) -> None:
        if self.original_bytes < 0:
            raise InvariantViolation("BoundedRunOutput.original_bytes must be >= 0")


@runtime_checkable
class TestSnapshotProvisioner(Protocol):
    """Builds/verifies the exact-byte snapshot and owns its cleanup (CP2-backed)."""

    __test__: ClassVar[bool] = False  # domain term; not a pytest test class

    def provision(self, approved_read_scope: tuple[str, ...]) -> ProvisionedSnapshot:
        """Materialize + verify the approved read scope into an isolated snapshot."""
        ...

    def cleanup(self, snapshot: ProvisionedSnapshot) -> CleanupOutcome:
        """Idempotently release the snapshot/runtime artifacts; report any impact."""
        ...


@runtime_checkable
class TestOutputReader(Protocol):
    """Optional: returns bounded/redacted run output for the counts parser."""

    __test__: ClassVar[bool] = False  # domain term; not a pytest test class

    def read(self, runtime_output_ref: str) -> BoundedRunOutput | None:
        """Return bounded run output, or ``None`` when output is unavailable."""
        ...
