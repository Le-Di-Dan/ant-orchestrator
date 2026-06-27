"""CP1 — Test Ant contract guarantees: read-only authority, no argv/shell, JSON-safe."""

from __future__ import annotations

import dataclasses
import json

import pytest

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.test_isolation import (
    EnvironmentPolicy,
    IsolatedExecutionSpec,
    IsolationCapability,
    IsolationStatus,
    NetworkPolicy,
)
from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)

# --- TestTask intent ----------------------------------------------------------


def test_test_task_accepts_command_key_and_targets() -> None:
    task = TestTask(
        task_ref="task-1",
        logical_action_id="task-1-test",
        command_key="pytest.acceptance",
        targets=("tests/unit", "src/pkg/mod.py"),
    )
    assert task.command_key == "pytest.acceptance"


def test_test_task_rejects_free_form_argv() -> None:
    with pytest.raises(InvariantViolation):
        TestTask(task_ref="t", logical_action_id="a", command_key="pytest -k secret")


def test_test_task_rejects_absolute_or_traversal_targets() -> None:
    for bad in ("/etc/passwd", "..\\..\\win", "C:\\Windows"):
        with pytest.raises(InvariantViolation):
            TestTask(task_ref="t", logical_action_id="a", command_key="pytest", targets=(bad,))


def test_test_task_has_no_write_or_command_fields() -> None:
    names = {f.name for f in dataclasses.fields(TestTask)}
    assert "command_argv" not in names
    assert not any("write" in n for n in names)
    assert not any("env" in n for n in names)


# --- TestExecutionScope authority (read-only) ---------------------------------


def test_scope_is_read_only_by_construction() -> None:
    names = {f.name for f in dataclasses.fields(TestExecutionScope)}
    forbidden_fragments = ("write", "operation", "mutat", "git", "argv", "env")
    for fragment in forbidden_fragments:
        assert not any(fragment in n for n in names), f"scope exposes {fragment!r}"


def test_scope_requires_read_scope_and_rejects_absolute() -> None:
    with pytest.raises(InvariantViolation):
        TestExecutionScope(
            attempt_id="a",
            run_id="r",
            logical_action_id="l",
            canonical_read_scope=("/abs/path",),
            command_profile_key="pytest",
            idempotency_key="k",
        )


def test_scope_valid_instance() -> None:
    scope = TestExecutionScope(
        attempt_id="a",
        run_id="r",
        logical_action_id="l",
        canonical_read_scope=("tests", "src"),
        command_profile_key="pytest.acceptance",
        idempotency_key="k",
        isolation_ref="container",
    )
    assert scope.isolation_ref == "container"


# --- IsolatedExecutionSpec (no Docker CLI / host shell) -----------------------


def test_spec_rejects_shell_strings_and_flags() -> None:
    base = dict(
        snapshot_ref="snap-1",
        runtime_output_ref="out-1",
        command_profile_key="pytest",
        timeout_ms=1000,
        max_processes=8,
    )
    with pytest.raises(InvariantViolation):
        IsolatedExecutionSpec(**{**base, "snapshot_ref": "docker run --rm -v x:/y"})
    with pytest.raises(InvariantViolation):
        IsolatedExecutionSpec(**{**base, "image_ref": "--privileged"})
    with pytest.raises(InvariantViolation):
        IsolatedExecutionSpec(**{**base, "runtime_output_ref": "/host/abs/path"})


def test_spec_defaults_are_fail_safe() -> None:
    spec = IsolatedExecutionSpec(
        snapshot_ref="snap-1",
        runtime_output_ref="out-1",
        command_profile_key="pytest",
        timeout_ms=1000,
        max_processes=8,
    )
    assert spec.network_policy is NetworkPolicy.DISABLED
    assert spec.environment_policy is EnvironmentPolicy.SANITIZED_MINIMAL
    assert spec.non_root and spec.read_only_root


def test_spec_rejects_non_positive_limits() -> None:
    with pytest.raises(InvariantViolation):
        IsolatedExecutionSpec(
            snapshot_ref="s",
            runtime_output_ref="o",
            command_profile_key="pytest",
            timeout_ms=0,
            max_processes=8,
        )


def test_capability_unavailable_requires_reason_and_is_json_safe() -> None:
    with pytest.raises(InvariantViolation):
        IsolationCapability(status=IsolationStatus.UNAVAILABLE)
    cap = IsolationCapability(
        status=IsolationStatus.UNAVAILABLE,
        reason_code=TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE,
    )
    assert not cap.is_available
    assert json.loads(json.dumps(cap.to_state_dict()))["status"] == "unavailable"


# --- TestExecutionOutcome (graph-facing, JSON-safe) ---------------------------


def test_outcome_success_has_no_failure_facets() -> None:
    outcome = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-1")
    assert json.loads(json.dumps(outcome.to_state_dict()))["outcome"] == "success"


def test_outcome_failure_requires_facets() -> None:
    with pytest.raises(InvariantViolation):
        TestExecutionOutcome(outcome=WorkerOutcome.PERMANENT_FAILURE, attempt_ref="att-1")


def test_outcome_rejects_provider_invocation() -> None:
    with pytest.raises(InvariantViolation):
        TestExecutionOutcome(
            outcome=WorkerOutcome.SUCCESS, attempt_ref="att-1", provider_invoked=True
        )


def test_outcome_failure_is_json_safe() -> None:
    outcome = TestExecutionOutcome(
        outcome=WorkerOutcome.ESCALATION,
        attempt_ref="att-1",
        disposition=RecoveryDisposition.ESCALATE,
        reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
        category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
        evidence_refs=("evidence:1",),
    )
    payload = outcome.to_state_dict()
    assert json.loads(json.dumps(payload)) == payload
