"""Walking-skeleton graph tests via the runner (CP3)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)
from ant_orchestrator.config.constants import GRAPH_STATE_SCHEMA_VERSION
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workflows.state import new_graph_state
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME
from tests.support.scripted_worker import ScriptedStubAdapter


class _CountingWorker:
    def __init__(self, outcome: WorkerOutcome = WorkerOutcome.SUCCESS) -> None:
        self.calls = 0
        self._outcome = outcome

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        self.calls += 1
        return WorkerExecutionResult(outcome=self._outcome, detail="x")


def _runner(tmp_path: Path, worker: object) -> WorkflowRunner:
    return WorkflowRunner(
        worker=worker,  # type: ignore[arg-type]
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
    )


def _initial(run_id: str = "R1") -> object:
    return new_graph_state(task_id="T1", workflow_run_id=run_id, base_retry_limit=2)


def test_happy_path_reaches_end_with_single_execution(tmp_path: Path) -> None:
    worker = _CountingWorker()
    result = _runner(tmp_path, worker).invoke(_initial(), thread_id="wf:R1")
    assert result.reached_end is True
    assert result.final_outcome == "completed"
    assert worker.calls == 1


def test_graph_state_schema_is_preserved(tmp_path: Path) -> None:
    result = _runner(tmp_path, _CountingWorker()).invoke(_initial(), thread_id="wf:R1")
    assert result.final_state["graph_state_schema_version"] == GRAPH_STATE_SCHEMA_VERSION


def test_retry_path_reuses_cp2_router_and_increments_counter_once(tmp_path: Path) -> None:
    worker = ScriptedStubAdapter([WorkerOutcome.RETRYABLE_FAILURE, WorkerOutcome.SUCCESS])
    result = _runner(tmp_path, worker).invoke(_initial("R2"), thread_id="wf:R2")
    assert result.final_outcome == "completed"
    assert result.final_state["retry_count"] == 1  # exactly one retry
    assert result.final_state["base_retry_limit"] == 2  # snapshot unchanged
    assert result.final_state["retry_extension_count"] == 0


def test_regroup_path_routes_back_to_plan(tmp_path: Path) -> None:
    worker = ScriptedStubAdapter([WorkerOutcome.REVIEW_REGROUP, WorkerOutcome.SUCCESS])
    result = _runner(tmp_path, worker).invoke(_initial("R3"), thread_id="wf:R3")
    assert result.final_outcome == "completed"
    assert result.final_state["regroup_count"] == 1


def test_permanent_failure_routes_to_failed_terminal(tmp_path: Path) -> None:
    worker = _CountingWorker(WorkerOutcome.PERMANENT_FAILURE)
    result = _runner(tmp_path, worker).invoke(_initial("R4"), thread_id="wf:R4")
    assert result.reached_end is True
    assert result.final_outcome == "failed"
