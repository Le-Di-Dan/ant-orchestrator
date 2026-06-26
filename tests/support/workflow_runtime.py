"""Shared helpers to build a WorkflowRunner in tests (test-only)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionPort,
    WorkerExecutionResult,
    WorkerOutcome,
)
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workflows.state import GraphState, new_graph_state
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME


class CountingWorker:
    """A deterministic worker that records how many times it executed."""

    def __init__(self, outcome: WorkerOutcome = WorkerOutcome.SUCCESS) -> None:
        self.calls = 0
        self._outcome = outcome

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        self.calls += 1
        return WorkerExecutionResult(outcome=self._outcome, detail="x")


def build_runner(
    tmp_path: Path,
    worker: WorkerExecutionPort,
    *,
    definition_version: int = WORKFLOW_DEFINITION_VERSION,
) -> WorkflowRunner:
    return WorkflowRunner(
        worker=worker,
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        definition_version=definition_version,
    )


def initial_state(run_id: str = "R1", *, base_retry_limit: int = 2) -> GraphState:
    return new_graph_state(task_id="T1", workflow_run_id=run_id, base_retry_limit=base_retry_limit)
