"""CP3 — StructuredTestReport invariants + JSON-safety (no Docker, §7)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from ant_orchestrator.config.constants import TEST_REPORT_SCHEMA_VERSION
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
)
from ant_orchestrator.workers.test.provisioning import CleanupStatus
from ant_orchestrator.workers.test.report import (
    StructuredTestReport,
    TestCounts,
    TestProcessStatus,
    TestResult,
)

_SECRET = "AKIA0SECRET0SENTINEL0"


def _success(**over: Any) -> StructuredTestReport:
    base: dict[str, Any] = dict(
        run_ref="run-1",
        attempt_ref="att-1",
        logical_action_ref="task-1-test",
        worker_kind="test",
        command_key="pytest.acceptance",
        command_profile_version=1,
        sanitized_argv=("python", "-m", "pytest"),
        argv_digest="d" * 16,
        approved_targets=("tests/unit",),
        process_status=TestProcessStatus.COMPLETED,
        test_result=TestResult.PASSED,
        counts=TestCounts.unavailable(),
        snapshot_verified=True,
        cleanup_status=CleanupStatus.CLEAN,
        diagnostic_hint="Acceptance suite passed.",
    )
    base.update(over)
    return StructuredTestReport(**base)


def _failure(**over: Any) -> StructuredTestReport:
    facets: dict[str, Any] = dict(
        test_result=TestResult.FAILED,
        failure_category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
        reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
        transience=Transience.DETERMINISTIC,
        recovery_disposition=RecoveryDisposition.ESCALATE,
        diagnostic_hint="deterministic failures",
    )
    facets.update(over)
    return _success(**facets)


def test_success_report_is_valid_and_has_no_facets() -> None:
    report = _success()
    assert report.is_success
    assert report.failure_category is None
    assert report.report_schema_version == TEST_REPORT_SCHEMA_VERSION


def test_success_with_failure_facet_rejected() -> None:
    with pytest.raises(InvariantViolation):
        _success(failure_category=FailureCategory.UNKNOWN)


def test_failure_missing_facet_rejected() -> None:
    with pytest.raises(InvariantViolation):
        _success(test_result=TestResult.FAILED, failure_category=FailureCategory.UNKNOWN)


def test_failure_report_with_full_facets_valid() -> None:
    report = _failure()
    assert not report.is_success
    assert report.reason_code is TestReasonCode.DETERMINISTIC_TEST_FAILURE


def test_no_tests_cannot_be_pass() -> None:
    # NO_TESTS with no facets is non-success -> facets required, so it can never be a pass.
    with pytest.raises(InvariantViolation):
        _success(test_result=TestResult.NO_TESTS)


def test_unverified_snapshot_cannot_report_pass() -> None:
    with pytest.raises(InvariantViolation):
        _success(snapshot_verified=False)


def test_isolation_unavailable_has_no_fake_exit_code() -> None:
    with pytest.raises(InvariantViolation):
        _failure(
            process_status=TestProcessStatus.ISOLATION_UNAVAILABLE,
            test_result=TestResult.ERROR,
            failure_category=FailureCategory.EXECUTION_ISOLATION_UNAVAILABLE,
            reason_code=TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE,
            recovery_disposition=RecoveryDisposition.ESCALATE,
            exit_code=1,
        )


def test_cancelled_requires_terminal_cancelled_disposition() -> None:
    with pytest.raises(InvariantViolation):
        _failure(
            process_status=TestProcessStatus.CANCELLED,
            test_result=TestResult.ERROR,
            failure_category=FailureCategory.UNKNOWN,
            reason_code=TestReasonCode.EXECUTION_CANCELLED,
            transience=Transience.DETERMINISTIC,
            recovery_disposition=RecoveryDisposition.ESCALATE,
        )


def test_cancelled_report_valid() -> None:
    report = _failure(
        process_status=TestProcessStatus.CANCELLED,
        test_result=TestResult.ERROR,
        failure_category=FailureCategory.UNKNOWN,
        reason_code=TestReasonCode.EXECUTION_CANCELLED,
        transience=Transience.DETERMINISTIC,
        recovery_disposition=RecoveryDisposition.TERMINAL_CANCELLED,
    )
    assert report.recovery_disposition is RecoveryDisposition.TERMINAL_CANCELLED


def test_provider_invoked_rejected() -> None:
    with pytest.raises(InvariantViolation):
        _success(provider_invoked=True)


def test_counts_unavailable_accepted() -> None:
    report = _success(counts=TestCounts.unavailable())
    assert report.counts.to_state_dict() == {"available": False}


def test_host_absolute_path_rejected_in_argv() -> None:
    with pytest.raises(InvariantViolation):
        _success(sanitized_argv=("python", "C:\\secrets\\x.py"))


def test_host_absolute_path_rejected_in_target() -> None:
    with pytest.raises(InvariantViolation):
        _success(approved_targets=("/etc/passwd",))


def test_multiline_traceback_rejected_in_excerpt() -> None:
    with pytest.raises(InvariantViolation):
        _failure(failure_excerpts=("Traceback (most recent call last):\n  File ...",))


def test_excerpt_count_bounded() -> None:
    with pytest.raises(InvariantViolation):
        _failure(failure_excerpts=tuple(f"line {i}" for i in range(20)))


def test_evidence_refs_bounded() -> None:
    with pytest.raises(InvariantViolation):
        _success(evidence_refs=tuple(f"e{i}" for i in range(64)))


def test_json_round_trip_and_no_secret_leak() -> None:
    report = _failure(
        failure_excerpts=("assert 1 == 2",),
        evidence_refs=("audit:abc123",),
        diagnostic_hint="deterministic failures; Queen review required",
    )
    payload = json.dumps(report.to_state_dict())
    assert _SECRET not in payload
    restored = json.loads(payload)
    assert restored["test_result"] == "failed"
    assert restored["reason_code"] == "deterministic_test_failure"
    assert restored["provider_invoked"] is False
