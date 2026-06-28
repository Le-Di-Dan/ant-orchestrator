"""CP4 — workflow versioning tests (§11.10, §8).

Verifies:
* WORKFLOW_DEFINITION_VERSION == 4 (topology changed: node test added).
* GRAPH_STATE_SCHEMA_VERSION == 2 (new fields are additive optional, no schema bump).
* Version-3 checkpoints fail closed (WorkflowDefinitionMismatch) when run against version-4 graph.
* New compact test fields are additive optional (schema version unchanged at 2).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.workflows.state import (
    GRAPH_STATE_SCHEMA_VERSION,
    GraphState,
    new_graph_state,
)
from ant_orchestrator.application.ports.workflow_runner import WorkflowDefinitionMismatch


# ---------------------------------------------------------------------------
# Version constants
# ---------------------------------------------------------------------------


def test_workflow_definition_version_is_4() -> None:
    assert WORKFLOW_DEFINITION_VERSION == 4


def test_graph_state_schema_version_is_2() -> None:
    assert GRAPH_STATE_SCHEMA_VERSION == 2


# ---------------------------------------------------------------------------
# New compact test fields are present in GraphState TypedDict
# ---------------------------------------------------------------------------


def test_new_test_fields_present_in_graph_state() -> None:
    state: GraphState = new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=1)
    # All new CP4 fields must be present (defaulting to None / []).
    assert "test_status" in state
    assert "test_outcome" in state
    assert "test_failure_category" in state
    assert "test_reason_code" in state
    assert "test_recovery_disposition" in state
    assert "test_attempt_ref" in state
    assert "test_logical_action_ref" in state
    assert "test_evidence_refs" in state


def test_new_test_fields_default_to_none_or_empty() -> None:
    state = new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=1)
    assert state["test_status"] is None
    assert state["test_outcome"] is None
    assert state["test_failure_category"] is None
    assert state["test_reason_code"] is None
    assert state["test_recovery_disposition"] is None
    assert state["test_attempt_ref"] is None
    assert state["test_logical_action_ref"] is None
    assert state["test_evidence_refs"] == []


# ---------------------------------------------------------------------------
# Version-3 checkpoint → WorkflowDefinitionMismatch
# ---------------------------------------------------------------------------


def test_version3_checkpoint_fails_closed_against_version4_graph(tmp_path: Path) -> None:
    """Version guard is checked at application-service layer via check_definition_version.

    A WorkflowRun stores workflow_definition_version=3. When the v4 runner's
    check_definition_version(3) is called (as all application services do), it must raise
    WorkflowDefinitionMismatch. This is the correct test: the mechanism is the explicit
    call from the service, not inside runner.resume().
    """
    from ant_orchestrator.application.ports.worker import WorkerActionIntent, WorkerExecutionResult, WorkerOutcome
    from ant_orchestrator.energy.enforcement import EnforcementPolicy
    from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
    from ant_orchestrator.workflows.runner import WorkflowRunner
    from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME

    class _StubWorker:
        def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
            return WorkerExecutionResult(outcome=WorkerOutcome.SUCCESS, detail="ok")

    # Runner configured as version 4 (current topology).
    runner_v4 = WorkflowRunner(
        worker=_StubWorker(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        definition_version=4,
    )
    # Service detects that the run was created with version 3 → fail closed.
    with pytest.raises(WorkflowDefinitionMismatch):
        runner_v4.check_definition_version(3)


# ---------------------------------------------------------------------------
# Graph state schema backward compat: existing fields survive new fields
# ---------------------------------------------------------------------------


def test_existing_fields_not_broken_by_new_cp4_fields() -> None:
    state = new_graph_state(task_id="TASK-X", workflow_run_id="WF-X", base_retry_limit=3)
    # Core fields that existed before CP4.
    assert state["task_id"] == "TASK-X"
    assert state["workflow_run_id"] == "WF-X"
    assert state["base_retry_limit"] == 3
    assert "retry_count" in state
    assert "evidence_refs" in state


# ---------------------------------------------------------------------------
# TestExecutionOutcome.is_cancelled property
# ---------------------------------------------------------------------------


def test_is_cancelled_property_true_for_terminal_cancelled() -> None:
    from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
    from ant_orchestrator.application.ports.worker import WorkerOutcome
    from ant_orchestrator.core.domain.test_failure import FailureCategory, RecoveryDisposition, TestReasonCode

    outcome = TestExecutionOutcome(
        outcome=WorkerOutcome.PERMANENT_FAILURE,
        attempt_ref="att-1",
        disposition=RecoveryDisposition.TERMINAL_CANCELLED,
        reason_code=TestReasonCode.EXECUTION_CANCELLED,
        category=FailureCategory.UNKNOWN,
    )
    assert outcome.is_cancelled is True


def test_is_cancelled_property_false_for_terminal_failed() -> None:
    from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
    from ant_orchestrator.application.ports.worker import WorkerOutcome
    from ant_orchestrator.core.domain.test_failure import FailureCategory, RecoveryDisposition, TestReasonCode

    outcome = TestExecutionOutcome(
        outcome=WorkerOutcome.PERMANENT_FAILURE,
        attempt_ref="att-1",
        disposition=RecoveryDisposition.TERMINAL_FAILED,
        reason_code=TestReasonCode.EXECUTABLE_MISSING,
        category=FailureCategory.EXECUTABLE_MISSING,
    )
    assert outcome.is_cancelled is False


def test_is_cancelled_property_false_when_no_disposition() -> None:
    from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
    from ant_orchestrator.application.ports.worker import WorkerOutcome

    outcome = TestExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="att-1")
    assert outcome.is_cancelled is False
