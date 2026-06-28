"""Immutable, durable-facing structured test report (PHASE_6_PLAN CP3, §D.6/§7).

A :class:`StructuredTestReport` is assembled ENTIRELY from system facts (isolation result,
exit/process status, snapshot manifest, classification). It is bounded and sanitized by
construction: no raw stdout/stderr, no exception/traceback, no provider response, no
secret, no host absolute path, no Docker argv carrying a host mount. Only the sanitized
inner argv (``python -m pytest`` + in-scope targets) and an argv digest are kept.

The report owns its own validation invariants (§7.3): a success report carries no failure
facets; a failure/cancelled report carries the full classification; ``no_tests`` and an
unverified snapshot can never report a pass; an unavailable backend never records a fake
exit code. Pure data + invariants — no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.config.constants import (
    MAX_TEST_DIAGNOSTIC_HINT_CHARS,
    MAX_TEST_EVIDENCE_REFS,
    MAX_TEST_EXCERPT_CHARS,
    MAX_TEST_FAILURE_EXCERPTS,
    MAX_TEST_REPORT_TARGETS,
    TEST_REPORT_SCHEMA_VERSION,
)
from ant_orchestrator.core.domain.enums import _StrEnum
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
)
from ant_orchestrator.workers.test.provisioning import CleanupStatus


class TestProcessStatus(_StrEnum):
    """Process-level status of the run (superset of CP2 ``IsolatedRunStatus`` + interrupted)."""

    __test__ = False  # domain term; not a pytest test class

    COMPLETED = "completed"
    TIMEOUT = "timeout"
    INTERRUPTED = "interrupted"
    CANCELLED = "cancelled"
    LAUNCH_FAILED = "launch_failed"
    ISOLATION_UNAVAILABLE = "isolation_unavailable"
    ISOLATION_SETUP_FAILED = "isolation_setup_failed"


class TestResult(_StrEnum):
    """Acceptance result of the suite (richer than CP1 ``TestOutcome`` PASSED/FAILED)."""

    __test__ = False  # domain term; not a pytest test class

    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    NO_TESTS = "no_tests"


@dataclass(frozen=True, slots=True)
class TestCounts:
    """Per-bucket test counts, or an explicit ``unavailable`` (never fabricated)."""

    __test__ = False  # domain term; not a pytest test class

    available: bool = False
    passed: int = 0
    failed: int = 0
    errors: int = 0
    skipped: int = 0
    xfailed: int = 0
    xpassed: int = 0

    def __post_init__(self) -> None:
        for name in ("passed", "failed", "errors", "skipped", "xfailed", "xpassed"):
            if getattr(self, name) < 0:
                raise InvariantViolation(f"TestCounts.{name} must be >= 0")

    @classmethod
    def unavailable(cls) -> TestCounts:
        """Counts could not be parsed; the test result still stands on exit/process facts."""
        return cls(available=False)

    def to_state_dict(self) -> dict[str, object]:
        if not self.available:
            return {"available": False}
        return {
            "available": True,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "xfailed": self.xfailed,
            "xpassed": self.xpassed,
        }


def _assert_safe_text(value: str, field_name: str) -> None:
    """Reject newlines/CR (no multiline traceback) and host absolute paths."""
    if "\n" in value or "\r" in value:
        raise InvariantViolation(f"{field_name} must be single-line (no raw output/traceback)")
    if value.startswith(("/", "\\")) or (
        len(value) >= 2 and value[1] == ":" and value[0].isalpha()
    ):
        raise InvariantViolation(f"{field_name} must not contain a host absolute path")


@dataclass(frozen=True, slots=True)
class StructuredTestReport:
    """Bounded, sanitized, JSON-safe report of one Test Ant run (§D.6)."""

    __test__ = False  # domain term; not a pytest test class

    run_ref: str
    attempt_ref: str
    logical_action_ref: str
    worker_kind: str
    command_key: str
    command_profile_version: int
    sanitized_argv: tuple[str, ...]
    argv_digest: str
    approved_targets: tuple[str, ...]
    process_status: TestProcessStatus
    test_result: TestResult
    counts: TestCounts
    snapshot_verified: bool
    cleanup_status: CleanupStatus
    diagnostic_hint: str
    duration_ms: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    snapshot_manifest_digest: str | None = None
    isolation_backend_ref: str | None = None
    isolation_image_ref: str | None = None
    isolation_status: str | None = None
    output_truncated: bool = False
    output_original_bytes: int = 0
    output_redaction_applied: bool = False
    failure_excerpts: tuple[str, ...] = field(default_factory=tuple)
    failure_category: FailureCategory | None = None
    reason_code: TestReasonCode | None = None
    transience: Transience | None = None
    recovery_disposition: RecoveryDisposition | None = None
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    energy_impact_ref: str | None = None
    provider_invoked: bool = False
    report_schema_version: int = TEST_REPORT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        self._validate_identity()
        self._validate_bounds()
        self._validate_consistency()

    # --- invariants ----------------------------------------------------------
    def _validate_identity(self) -> None:
        if self.report_schema_version != TEST_REPORT_SCHEMA_VERSION:
            raise InvariantViolation("StructuredTestReport.report_schema_version mismatch")
        for name in (
            "run_ref",
            "attempt_ref",
            "logical_action_ref",
            "worker_kind",
            "command_key",
            "argv_digest",
        ):
            if not getattr(self, name):
                raise InvariantViolation(f"StructuredTestReport.{name} must be non-empty")
        if self.provider_invoked:
            raise InvariantViolation("Test Ant never invokes a provider")
        if self.duration_ms < 0 or self.output_original_bytes < 0:
            raise InvariantViolation("StructuredTestReport counters must be >= 0")

    def _validate_bounds(self) -> None:
        if len(self.diagnostic_hint) > MAX_TEST_DIAGNOSTIC_HINT_CHARS:
            raise InvariantViolation("StructuredTestReport.diagnostic_hint exceeds the bound")
        _assert_safe_text(self.diagnostic_hint, "diagnostic_hint")
        if len(self.failure_excerpts) > MAX_TEST_FAILURE_EXCERPTS:
            raise InvariantViolation("StructuredTestReport.failure_excerpts exceeds the bound")
        for excerpt in self.failure_excerpts:
            if len(excerpt) > MAX_TEST_EXCERPT_CHARS:
                raise InvariantViolation("StructuredTestReport failure excerpt exceeds the bound")
            _assert_safe_text(excerpt, "failure_excerpts")
        if len(self.evidence_refs) > MAX_TEST_EVIDENCE_REFS:
            raise InvariantViolation("StructuredTestReport.evidence_refs exceeds the bound")
        if len(self.approved_targets) > MAX_TEST_REPORT_TARGETS:
            raise InvariantViolation("StructuredTestReport.approved_targets exceeds the bound")
        for arg in self.sanitized_argv:
            _assert_safe_text(arg, "sanitized_argv")
        for target in self.approved_targets:
            _assert_safe_text(target, "approved_targets")

    def _validate_consistency(self) -> None:
        if self.exit_code is not None and self.process_status not in (
            TestProcessStatus.COMPLETED,
            TestProcessStatus.INTERRUPTED,
        ):
            raise InvariantViolation("exit_code is only valid for a completed/interrupted process")
        if not self.snapshot_verified and self.test_result is TestResult.PASSED:
            raise InvariantViolation("an unverified snapshot can never report a pass")
        if self.is_success:
            if any(f is not None for f in self._facets):
                raise InvariantViolation("a success report must not carry failure facets")
            return
        if any(f is None for f in self._facets):
            raise InvariantViolation("a non-success report requires the full classification")
        if self.recovery_disposition is RecoveryDisposition.TERMINAL_CANCELLED:
            if self.reason_code is not TestReasonCode.EXECUTION_CANCELLED:
                raise InvariantViolation(
                    "a cancelled report requires the EXECUTION_CANCELLED reason"
                )
        if self.process_status is TestProcessStatus.CANCELLED:
            if self.recovery_disposition is not RecoveryDisposition.TERMINAL_CANCELLED:
                raise InvariantViolation(
                    "a cancelled process requires TERMINAL_CANCELLED disposition"
                )

    @property
    def _facets(self) -> tuple[object | None, ...]:
        return (self.failure_category, self.reason_code, self.transience, self.recovery_disposition)

    @property
    def is_success(self) -> bool:
        """A pass: the suite completed and every test passed (no failure facets)."""
        return (
            self.process_status is TestProcessStatus.COMPLETED
            and self.test_result is TestResult.PASSED
        )

    def to_state_dict(self) -> dict[str, object]:
        """Render as a JSON-safe dict for evidence/handoff (no raw output/host path)."""
        return {
            "report_schema_version": self.report_schema_version,
            "run_ref": self.run_ref,
            "attempt_ref": self.attempt_ref,
            "logical_action_ref": self.logical_action_ref,
            "worker_kind": self.worker_kind,
            "command_key": self.command_key,
            "command_profile_version": self.command_profile_version,
            "sanitized_argv": list(self.sanitized_argv),
            "argv_digest": self.argv_digest,
            "approved_targets": list(self.approved_targets),
            "process_status": self.process_status.value,
            "test_result": self.test_result.value,
            "counts": self.counts.to_state_dict(),
            "snapshot_verified": self.snapshot_verified,
            "snapshot_manifest_digest": self.snapshot_manifest_digest,
            "cleanup_status": self.cleanup_status.value,
            "isolation_backend_ref": self.isolation_backend_ref,
            "isolation_image_ref": self.isolation_image_ref,
            "isolation_status": self.isolation_status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "exit_code": self.exit_code,
            "output_truncated": self.output_truncated,
            "output_original_bytes": self.output_original_bytes,
            "output_redaction_applied": self.output_redaction_applied,
            "failure_excerpts": list(self.failure_excerpts),
            "diagnostic_hint": self.diagnostic_hint,
            "failure_category": self.failure_category.value if self.failure_category else None,
            "reason_code": self.reason_code.value if self.reason_code else None,
            "transience": self.transience.value if self.transience else None,
            "recovery_disposition": (
                self.recovery_disposition.value if self.recovery_disposition else None
            ),
            "evidence_refs": list(self.evidence_refs),
            "energy_impact_ref": self.energy_impact_ref,
            "provider_invoked": self.provider_invoked,
        }
