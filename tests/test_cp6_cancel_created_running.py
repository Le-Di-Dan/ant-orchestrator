"""CP6 — CancelTask: CREATED, RUNNING, and race cancel-vs-complete tests."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ant_orchestrator.config.constants import CANCEL_REQUESTED_STATUS
from ant_orchestrator.core.domain.enums import TaskStatus, WorkflowRunStatus
from ant_orchestrator.core.domain.value_objects import TaskId, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_completed_task,
    add_task,
    build_cancel_svc,
    build_services,
    create_running_run,
    make_runner_with_probe,
    uow_factory,
)
from tests.support.workflow_runtime import CountingWorker

# ---------------------------------------------------------------------------
# CREATED cancellation
# ---------------------------------------------------------------------------


def test_created_cancel_sets_task_cancelled(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CREATED task with no WorkflowRun → cancel → Task CANCELLED immediately."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    outcome = cancel_svc.cancel("T1")

    assert outcome.status == TaskStatus.CANCELLED.value
    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
    assert task.status == TaskStatus.CANCELLED
    assert active_run is None


def test_created_cancel_no_workflow_run_created(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CREATED cancel must not create any WorkflowRun row."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    cancel_svc.cancel("T1")

    with sqlite3.connect(str(database.path)) as conn:
        rows = conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()
    assert rows[0] == 0


def test_created_cancel_idempotent(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Cancelling an already-CANCELLED task returns the terminal status without error."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    cancel_svc.cancel("T1")
    outcome2 = cancel_svc.cancel("T1")

    assert outcome2.status == TaskStatus.CANCELLED.value


def test_created_cancel_no_graph_invocation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """CREATED cancel must not invoke the graph; worker call count stays 0."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    cancel_svc.cancel("T1")

    assert worker.calls == 0


# ---------------------------------------------------------------------------
# RUNNING cancellation
# ---------------------------------------------------------------------------


def _add_running_run(
    database: Database,
    task_id: str,
    run_id: str,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> WorkflowRunId:
    run_id_vo = WorkflowRunId(run_id)
    add_task(database, task_id, clock=clock)
    create_running_run(database, run_id_vo, task_id, clock, id_gen)
    return run_id_vo


def test_running_cancel_returns_cancel_requested(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """cancel() on RUNNING task returns CANCEL_REQUESTED immediately."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    _add_running_run(database, "T1", "R1", clock, id_gen)

    outcome = cancel_svc.cancel("T1")

    assert outcome.status == CANCEL_REQUESTED_STATUS
    assert outcome.run_id == "R1"


def test_running_cancel_sets_cancel_requested_at_once(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """cancel_requested_at is set on first call; duplicate cancel is idempotent."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    run_id_vo = _add_running_run(database, "T1", "R1", clock, id_gen)

    cancel_svc.cancel("T1")
    with SqliteUnitOfWork(database) as uow:
        run_after_first = uow.workflow_runs.get(run_id_vo)
    assert run_after_first.cancel_requested_at is not None

    # Second cancel must be idempotent: timestamp unchanged, no error.
    cancel_svc.cancel("T1")
    with SqliteUnitOfWork(database) as uow:
        run_after_second = uow.workflow_runs.get(run_id_vo)
    assert run_after_second.cancel_requested_at == run_after_first.cancel_requested_at


def test_running_cancel_eventual_terminal_via_reinvoke(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """After CANCEL_REQUESTED, re-invoking RunWorkflow drives graph to CANCELLED terminal."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    _add_running_run(database, "T1", "R1", clock, id_gen)

    cancel_svc.cancel("T1")
    # Re-invoke: no checkpoint observed, probe fires → graph routes to cancelled node.
    outcome = run_svc.execute("T1")

    assert outcome.status == TaskStatus.CANCELLED.value
    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
    assert task.status == TaskStatus.CANCELLED
    assert active_run is None


def test_running_cancel_no_new_attempt_after_probe(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Probe fires before AttemptOrchestrator.before_execute; no ExecutionAttempt created."""
    worker = CountingWorker()
    from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator

    uow_f = uow_factory(database)
    from ant_orchestrator.workflows.cancellation_probe import CancellationProbe

    probe = CancellationProbe(uow_f)
    from ant_orchestrator.energy.enforcement import EnforcementPolicy
    from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
    from ant_orchestrator.workflows.runner import WorkflowRunner
    from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME

    orchestrator = AttemptOrchestrator(uow_f, clock=clock, ids=id_gen)
    runner = WorkflowRunner(
        worker=worker,
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        attempt_orchestrator=orchestrator,
        cancellation_probe=probe,
    )
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    _add_running_run(database, "T1", "R1", clock, id_gen)

    cancel_svc.cancel("T1")
    run_svc.execute("T1")

    with sqlite3.connect(str(database.path)) as conn:
        attempt_rows = conn.execute("SELECT COUNT(*) FROM execution_attempts").fetchone()
    assert attempt_rows[0] == 0


# ---------------------------------------------------------------------------
# Race cancel-vs-complete
# ---------------------------------------------------------------------------


def test_race_cancel_wins_complete_cannot_overwrite(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """If cancel terminates run as CANCELLED, CompletionFinalizer 'completed' is a no-op."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    _, _, _, _, complete = build_services(database, runner, clock, id_gen)
    run_id_vo = _add_running_run(database, "T1", "R1", clock, id_gen)

    # Step 1: cancel sets cancel_requested_at
    cancel_svc.cancel("T1")

    # Step 2: simulate cancel physically winning — set run/task to CANCELLED terminal
    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.get(run_id_vo)
        uow.workflow_runs.compare_and_set_status(
            run.with_status(WorkflowRunStatus.CANCELLED, now=clock.now()),
            expected=WorkflowRunStatus.RUNNING,
        )
        task = uow.tasks.get(TaskId("T1"))
        # Task is CREATED (create_running_run only inserts run, not task transition)
        uow.tasks.compare_and_set_status(
            task.with_status(TaskStatus.CANCELLED, now=clock.now()),
            expected=task.status,
        )

    # Step 3: CompletionFinalizer tries "completed" — run is already CANCELLED (terminal)
    # → returns early; CANCELLED must not be overwritten
    complete.finalize(run_id_vo, final_outcome="completed", checkpoint_id="ckpt-fake")

    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.get(run_id_vo)
        task = uow.tasks.get(TaskId("T1"))
    assert run.status == WorkflowRunStatus.CANCELLED
    assert task.status == TaskStatus.CANCELLED


def test_race_complete_wins_cancel_cannot_change_terminal(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """If completion finalizes first, a subsequent cancel returns the terminal status."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    _, _, _, _, complete = build_services(database, runner, clock, id_gen)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    add_completed_task(database, "T1", clock=clock)

    # Task is already COMPLETED (no active run); cancel should be idempotent.
    outcome = cancel_svc.cancel("T1")

    assert outcome.status == TaskStatus.COMPLETED.value


def test_race_cancel_transitions_not_duplicated(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Duplicate cancel on RUNNING must not insert duplicate status_transitions."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    cancel_svc = build_cancel_svc(database, runner, clock, id_gen)
    _add_running_run(database, "T1", "R1", clock, id_gen)

    cancel_svc.cancel("T1")
    cancel_svc.cancel("T1")  # idempotent; must not raise UNIQUE constraint

    with sqlite3.connect(str(database.path)) as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM status_transitions WHERE trigger = 'cancel_request'"
        ).fetchone()
    assert rows[0] == 1
