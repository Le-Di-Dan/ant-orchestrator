"""CP6 — checkpoint recovery (Scenario H and END reconciliation) tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.application.errors import CheckpointRecoveryError
from ant_orchestrator.core.domain.enums import TaskStatus
from ant_orchestrator.core.domain.value_objects import TaskId, WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_task,
    build_services,
    create_running_run,
    make_runner_with_probe,
)
from tests.support.workflow_runtime import CountingWorker


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


# ---------------------------------------------------------------------------
# Recovery — initial invoke not done vs. checkpoint lost (Scenario H)
# ---------------------------------------------------------------------------


def test_recovery_no_checkpoint_reconcile_returns_none(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """RUNNING + checkpoint_ever_observed=False → Reconciler returns None (safe to restart)."""
    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    run_id_vo = _add_running_run(database, "T1", "R1", clock, id_gen)

    result = reconciler.reconcile_run(run_id_vo)

    assert result is None


def test_recovery_observed_checkpoint_missing_fail_closed(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """RUNNING + checkpoint_ever_observed=True but no snapshot → CheckpointRecoveryError."""

    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    run_id_vo = _add_running_run(database, "T1", "R1", clock, id_gen)

    # Simulate: checkpoint was observed (e.g. run was at some point past first node)
    # but the checkpoint data is now missing from the checkpoints DB.
    with SqliteUnitOfWork(database) as uow:
        run = uow.workflow_runs.get(run_id_vo)
        uow.workflow_runs.update(run.with_checkpoint_observed("ckpt-lost", now=clock.now()))

    with pytest.raises(CheckpointRecoveryError, match="Scenario H"):
        reconciler.reconcile_run(run_id_vo)


# ---------------------------------------------------------------------------
# Recovery — checkpoint states (Scenario H and END reconciliation)
# ---------------------------------------------------------------------------


def test_recovery_end_checkpoint_no_rerun_uses_finalizer(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Reconciler on RUNNING run with END checkpoint uses CompletionFinalizer, not worker."""
    import uuid

    from ant_orchestrator.application.services.workflow_support import thread_id_for
    from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
    from ant_orchestrator.core.domain.enums import WorkflowRunStatus
    from ant_orchestrator.core.domain.value_objects import WorkflowRunId
    from ant_orchestrator.core.domain.workflow import WorkflowRun

    add_task(database, clock=clock)
    run_id_vo = WorkflowRunId(str(uuid.uuid4()))
    thread_id = thread_id_for(run_id_vo.value)
    now = clock.now()

    # Insert the WorkflowRun record BEFORE invoking so the probe can find it.
    run = WorkflowRun(
        id=run_id_vo,
        task_id=TaskId("T1"),
        thread_id=thread_id,
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
        initial_invoke_operation_id=f"op-{run_id_vo.value}",
        created_at=now,
        updated_at=now,
    )
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(run)

    # Invoke graph with probe-enabled runner (no cancel_requested_at → probe is no-op).
    worker = CountingWorker()
    runner_with_probe = make_runner_with_probe(tmp_path, worker, database)
    initial = runner_with_probe.build_initial_state(
        task_id="T1", workflow_run_id=run_id_vo.value, base_retry_limit=2
    )
    result = runner_with_probe.invoke(initial, thread_id=thread_id)
    assert result.final_outcome == "completed"
    worker_calls_after_invoke = worker.calls

    # Simulate crash: run stays RUNNING in state DB (CompletionFinalizer didn't run).
    # Build reconciler with the probe-enabled runner.
    _, _, reconciler, _, _ = build_services(database, runner_with_probe, clock, id_gen)
    outcome = reconciler.reconcile_run(run_id_vo)

    assert outcome is not None
    assert outcome.status == TaskStatus.COMPLETED.value
    # Worker must not run again during reconciliation (END checkpoint found).
    assert worker.calls == worker_calls_after_invoke


def test_recovery_corrupted_checkpoint_raises(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """RUNNING run with observed checkpoint but snapshot has no clear next state → fail closed."""
    import uuid

    from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
    from ant_orchestrator.core.domain.enums import WorkflowRunStatus
    from ant_orchestrator.core.domain.value_objects import WorkflowRunId
    from ant_orchestrator.core.domain.workflow import WorkflowRun

    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_id_vo = WorkflowRunId(str(uuid.uuid4()))
    now = clock.now()
    run = WorkflowRun(
        id=run_id_vo,
        task_id=TaskId("T1"),
        thread_id=f"wf:{run_id_vo.value}",
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
        initial_invoke_operation_id=f"op-{run_id_vo.value}",
        created_at=now,
        updated_at=now,
        checkpoint_ever_observed=True,
        last_observed_checkpoint_id="ckpt-missing",
    )
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(run)

    # Thread has no checkpoint in the checkpointer DB → snapshot is empty
    # But checkpoint_ever_observed=True → fail closed
    with pytest.raises(CheckpointRecoveryError, match="Scenario H"):
        reconciler.reconcile_run(run_id_vo)


def test_recovery_initial_invoke_not_done_returns_none(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """RUNNING run with checkpoint_ever_observed=False and no snapshot → reconciler returns None."""
    import uuid

    from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
    from ant_orchestrator.core.domain.enums import WorkflowRunStatus
    from ant_orchestrator.core.domain.value_objects import WorkflowRunId
    from ant_orchestrator.core.domain.workflow import WorkflowRun

    worker = CountingWorker()
    runner = make_runner_with_probe(tmp_path, worker, database)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_id_vo = WorkflowRunId(str(uuid.uuid4()))
    now = clock.now()
    run = WorkflowRun(
        id=run_id_vo,
        task_id=TaskId("T1"),
        thread_id=f"wf:{run_id_vo.value}",
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
        initial_invoke_operation_id=f"op-{run_id_vo.value}",
        created_at=now,
        updated_at=now,
        checkpoint_ever_observed=False,
    )
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(run)

    result = reconciler.reconcile_run(run_id_vo)

    assert result is None  # safe to re-invoke from START
