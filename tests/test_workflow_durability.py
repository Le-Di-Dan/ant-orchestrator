"""Durability + restart + thread-isolation tests (CP3)."""

from __future__ import annotations

from pathlib import Path

from tests.support.workflow_runtime import CountingWorker, build_runner, initial_state


def test_checkpoint_is_durable_across_a_new_connection(tmp_path: Path) -> None:
    # Invoke with durability="sync" (in build_runner -> runner.invoke), then read with
    # a brand-new runner => a brand-new SqliteSaver connection (no shared in-process state).
    build_runner(tmp_path, CountingWorker()).invoke(initial_state(), thread_id="wf:R1")

    fresh_reader = build_runner(tmp_path, CountingWorker())
    latest = fresh_reader.latest_state("wf:R1")
    assert latest.values.get("final_outcome") == "completed"
    assert latest.next_nodes == ()  # reached END


def test_history_records_super_steps_to_end(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker())
    runner.invoke(initial_state(), thread_id="wf:R1")
    history = runner.state_history("wf:R1")
    assert len(history) >= 4
    assert any(summary.values.get("final_outcome") == "completed" for summary in history)


def test_threads_do_not_share_state(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, CountingWorker())
    runner.invoke(initial_state("R1"), thread_id="wf:R1")
    # A different thread id has never been invoked: empty snapshot.
    assert runner.latest_state("wf:OTHER").values == {}
