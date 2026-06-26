"""Version-guard tests: fail closed on schema/definition mismatch (CP3)."""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.workflows.runner import (
    GraphStateSchemaMismatch,
    WorkflowDefinitionMismatch,
)
from tests.support.workflow_runtime import CountingWorker, build_runner, initial_state


def test_unknown_graph_state_schema_fails_closed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker())
    state = initial_state()
    state["graph_state_schema_version"] = 999  # not the supported version
    with pytest.raises(GraphStateSchemaMismatch):
        runner.invoke(state, thread_id="wf:R1")


def test_compatible_schema_runs_normally(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker())
    result = runner.invoke(initial_state(), thread_id="wf:R1")
    assert result.reached_end is True


def test_workflow_definition_mismatch_fails_closed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker(), definition_version=1)
    runner.check_definition_version(1)  # compatible: no raise
    with pytest.raises(WorkflowDefinitionMismatch):
        runner.check_definition_version(2)  # incompatible topology version
