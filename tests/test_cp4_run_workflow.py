"""CP4 — RunWorkflow integration tests.

Covers: fresh run → COMPLETED, terminal task guard, interrupt → AWAITING_APPROVAL,
idempotent re-enter, crash#2 re-finalize, crash#7 re-finalize,
CompletionFinalizer without ResumeOperation (happy-path, no approval gate).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.application.errors import WorkflowStateError
from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.workflow_support import (
    append_transition,
    thread_id_for,
)
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION, WORKFLOW_MAX_RETRIES
from ant_orchestrator.core.domain.enums import (
    TaskStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.core.domain.value_objects import (
    TaskId,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import WorkflowRun
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_completed_task,
    add_task,
    build_services,
    create_running_run,
    make_interrupt_runner,
    uow_factory,
)
from tests.support.workflow_factories import make_run
from tests.support.workflow_runtime import CountingWorker, build_runner

# ---------------------------------------------------------------------------
# Fresh run — gate ALLOW throughout
# ---------------------------------------------------------------------------


def test_run_workflow_fresh_no_interrupt(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Gate ALLOW throughout → worker executes once → COMPLETED immediately."""
    worker = CountingWorker()
    runner = build_runner(tmp_path, worker)
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    outcome = run_svc.execute("T1")

    assert outcome.status == TaskStatus.COMPLETED.value
    assert worker.calls == 1
    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
    assert task.status == TaskStatus.COMPLETED
    assert active_run is None


def test_run_workflow_terminal_task_raises(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Calling execute on an already-COMPLETED task raises WorkflowStateError."""
    add_completed_task(database, "T2", clock=clock)
    runner = build_runner(tmp_path, CountingWorker())
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)

    with pytest.raises(WorkflowStateError, match="terminal"):
        run_svc.execute("T2")


# ---------------------------------------------------------------------------
# Interrupt path (requires_significant_write gate)
# ---------------------------------------------------------------------------


def test_run_workflow_significant_write_produces_awaiting_approval(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Initial state with requires_significant_write → interrupt → AWAITING_APPROVAL."""
    runner = make_interrupt_runner(tmp_path, CountingWorker())
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    outcome = run_svc.execute("T1")

    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert outcome.approval_id is not None

    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
        active_run = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(active_run.id)

    assert task.status == TaskStatus.WAITING_FOR_APPROVAL
    assert active_run.status == WorkflowRunStatus.AWAITING_APPROVAL
    assert approval is not None
    assert approval.langgraph_interrupt_id is not None


def test_run_workflow_awaiting_reenter_returns_same_approval(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Re-running while AWAITING_APPROVAL returns the same approval_id (idempotent)."""
    runner = make_interrupt_runner(tmp_path, CountingWorker())
    run_svc, _, _, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    first = run_svc.execute("T1")
    second = run_svc.execute("T1")

    assert first.approval_id == second.approval_id
    assert second.status == TaskStatus.WAITING_FOR_APPROVAL.value


# ---------------------------------------------------------------------------
# CompletionFinalizer happy-path without ResumeOperation
# ---------------------------------------------------------------------------


def test_completion_finalizer_works_without_resume_operation(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Terminal happy-path: CompletionFinalizer finalizes correctly without ResumeOperation."""
    worker = CountingWorker()
    runner = build_runner(tmp_path, worker)
    uow_f = uow_factory(database)
    add_task(database, clock=clock)

    run_id = WorkflowRunId("R-noapproval")
    tid = thread_id_for(run_id.value)
    now = clock.now()
    run = WorkflowRun(
        id=run_id,
        task_id=TaskId("T1"),
        thread_id=tid,
        status=WorkflowRunStatus.RUNNING,
        workflow_definition_version=WORKFLOW_DEFINITION_VERSION,
        initial_invoke_operation_id="op-noapproval",
        created_at=now,
        updated_at=now,
    )
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(run)
        append_transition(
            uow.transitions,
            ids=id_gen,
            now=now,
            run_id=run_id,
            subject=TransitionSubject.RUN,
            to_status=WorkflowRunStatus.RUNNING.value,
            trigger=TransitionTrigger.RUN_CREATED,
            operation_id="op-noapproval",
        )

    initial = runner.build_initial_state(
        task_id="T1", workflow_run_id=run_id.value, base_retry_limit=WORKFLOW_MAX_RETRIES
    )
    result = runner.invoke(initial, thread_id=tid)
    assert result.reached_end

    complete = CompletionFinalizer(uow_f, clock=clock, ids=id_gen)
    outcome = complete.finalize(
        run_id,
        final_outcome=result.final_outcome,
        checkpoint_id=result.checkpoint_id,
        resume_operation_id=None,
    )
    assert outcome.status == TaskStatus.COMPLETED.value


# ---------------------------------------------------------------------------
# Reconciler crash windows
# ---------------------------------------------------------------------------


def test_reconciler_crash2_re_finalizes_approval(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Crash#2: RUNNING + interrupted snapshot + no Approval → Reconciler re-finalizes."""
    runner = make_interrupt_runner(tmp_path, CountingWorker())
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_id = WorkflowRunId("R-crash2")
    run = create_running_run(database, run_id, "T1", clock, id_gen)

    initial = runner.build_initial_state(
        task_id="T1", workflow_run_id=run_id.value, base_retry_limit=WORKFLOW_MAX_RETRIES
    )
    result = runner.invoke(initial, thread_id=run.thread_id)
    assert result.interrupt is not None

    outcome = reconciler.reconcile_run(run_id)

    assert outcome is not None
    assert outcome.status == TaskStatus.WAITING_FOR_APPROVAL.value
    assert outcome.approval_id is not None

    with SqliteUnitOfWork(database) as uow:
        active = uow.workflow_runs.find_active_by_task(TaskId("T1"))
        approval = uow.approvals.find_pending_by_run(run_id)
    assert active is not None
    assert active.status == WorkflowRunStatus.AWAITING_APPROVAL
    assert approval is not None


def test_reconciler_crash7_re_finalizes_completion(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Crash#7: RUNNING + END snapshot + no CompletionFinalizer → Reconciler fixes it."""
    worker = CountingWorker()
    runner = build_runner(tmp_path, worker)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, clock=clock)

    run_id = WorkflowRunId("R-crash7")
    run = create_running_run(database, run_id, "T1", clock, id_gen)

    initial = runner.build_initial_state(
        task_id="T1", workflow_run_id=run_id.value, base_retry_limit=WORKFLOW_MAX_RETRIES
    )
    result = runner.invoke(initial, thread_id=run.thread_id)
    assert result.reached_end

    outcome = reconciler.reconcile_run(run_id)

    assert outcome is not None
    assert outcome.status == TaskStatus.COMPLETED.value

    with SqliteUnitOfWork(database) as uow:
        task = uow.tasks.get(TaskId("T1"))
    assert task.status == TaskStatus.COMPLETED


def test_reconciler_returns_none_for_non_running_run(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Reconciler returns None when the run is already terminal."""
    add_task(database, "T2", clock=clock)
    with SqliteUnitOfWork(database) as uow:
        uow.workflow_runs.add(make_run("R-done", task_id="T2", status=WorkflowRunStatus.COMPLETED))

    runner = build_runner(tmp_path, CountingWorker())
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)

    outcome = reconciler.reconcile_run(WorkflowRunId("R-done"))
    assert outcome is None


def test_reconciler_task_returns_none_when_no_active_run(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """Reconciler.reconcile_task returns None when the task has no active run."""
    add_task(database, "T3", clock=clock)
    runner = build_runner(tmp_path, CountingWorker())
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)

    outcome = reconciler.reconcile_task("T3")
    assert outcome is None
