"""Serializer + state security tests (CP3): no pickle, reject unsupported objects."""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.workflows.state import GraphStateError
from tests.support.workflow_runtime import CountingWorker, build_runner, initial_state


def test_checkpoint_serializer_has_no_pickle_fallback() -> None:
    from ant_orchestrator.workflows.checkpointer import _safe_serializer

    assert _safe_serializer().pickle_fallback is False


def test_serializer_rejects_arbitrary_object_without_pickling() -> None:
    from ant_orchestrator.workflows.checkpointer import _safe_serializer

    class Custom:
        pass

    # With pickle fallback off, an arbitrary object is rejected (never silently pickled).
    with pytest.raises(TypeError):
        _safe_serializer().dumps_typed(Custom())


def test_primitive_state_checkpoints_and_restores(tmp_path: Path) -> None:
    build_runner(tmp_path, CountingWorker()).invoke(initial_state(), thread_id="wf:R1")
    latest = build_runner(tmp_path, CountingWorker()).latest_state("wf:R1")
    assert latest.values.get("final_outcome") == "completed"


def test_invoke_rejects_non_json_safe_state(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker())
    state = initial_state()
    state["plan"] = {"obj": object()}  # not JSON-safe; no secret/raw object may pass
    with pytest.raises(GraphStateError):
        runner.invoke(state, thread_id="wf:R1")
