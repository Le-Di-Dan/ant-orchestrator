"""CP8 correction — re-entry version guards (subprocess + application composition).

A run created under an incompatible ``workflow_definition_version`` (or a durable
snapshot with an unsupported ``graph_state_schema_version``) must fail closed on every
re-entry path — RunWorkflow re-entry, ResolveApproval, CancelTask (AWAITING) and the
Reconciler — without re-START, resume, worker call, or mutating the Approval /
ResumeOperation. Mismatches share the storage/recovery exit code (4).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ant_orchestrator.application.ports.workflow_runner import (
    GraphStateSchemaMismatch,
    WorkflowDefinitionMismatch,
)
from ant_orchestrator.core.domain.value_objects import WorkflowRunId
from ant_orchestrator.persistence.database import Database
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support import cp8_evidence as ev
from tests.support.cp4_helpers import add_task, build_services, create_running_run
from tests.support.cp8_harness import (
    cli_approve,
    cli_cancel,
    cli_run,
    driver,
    expect_ok,
    init_and_create,
)
from tests.support.workflow_runtime import CountingWorker, build_runner

_BAD_VERSION = ["--definition-version", "99"]


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


# ---------------------------------------------------------------------------
# Subprocess (public CLI) — re-entry over real composition
# ---------------------------------------------------------------------------


def test_run_reentry_definition_mismatch_fails_closed(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok("seed", driver("seed-running", workspace, task_id=task_id, extra=_BAD_VERSION))

    proc = cli_run(workspace, task_id)
    assert proc.returncode == 4
    assert proc.json()["error"]["type"] == "WorkflowDefinitionMismatch"
    assert ev.count_rows(workspace, "execution_attempts") == 0  # no re-START / worker


def test_approve_definition_mismatch_fails_closed_without_mutation(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok("run", driver("run", workspace, task_id=task_id, extra=["--significant-write"]))
    expect_ok(
        "set-version", driver("set-run-version", workspace, task_id=task_id, extra=_BAD_VERSION)
    )

    proc = cli_approve(workspace, task_id)
    assert proc.returncode == 4
    assert proc.json()["error"]["type"] == "WorkflowDefinitionMismatch"
    # The pending Approval/ResumeOperation are untouched.
    assert ev.approvals(workspace)[0]["status"] == "pending"
    assert ev.count_rows(workspace, "resume_operations") == 0
    assert ev.count_rows(workspace, "execution_attempts") == 0


def test_cancel_definition_mismatch_fails_closed_without_mutation(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)
    expect_ok("run", driver("run", workspace, task_id=task_id, extra=["--significant-write"]))
    expect_ok(
        "set-version", driver("set-run-version", workspace, task_id=task_id, extra=_BAD_VERSION)
    )

    proc = cli_cancel(workspace, task_id)
    assert proc.returncode == 4
    assert proc.json()["error"]["type"] == "WorkflowDefinitionMismatch"
    assert ev.approvals(workspace)[0]["status"] == "pending"
    assert ev.count_rows(workspace, "resume_operations") == 0


# ---------------------------------------------------------------------------
# Application composition (in-process) — Reconciler + schema guard
# ---------------------------------------------------------------------------


def test_reconciler_definition_mismatch_fails_closed(
    database: Database,
    tmp_path: Path,
    clock: FakeClock,
    id_gen: SequentialIdGenerator,
) -> None:
    """The Reconciler (not CLI-reachable) also guards the definition version."""
    worker = CountingWorker()
    runner = build_runner(tmp_path, worker)
    _, _, reconciler, _, _ = build_services(database, runner, clock, id_gen)
    add_task(database, "T1", clock=clock)
    run = create_running_run(database, WorkflowRunId("R1"), "T1", clock, id_gen)
    # Re-load with an incompatible stored definition version.
    with database.transaction() as conn:
        conn.execute(
            "UPDATE workflow_runs SET workflow_definition_version = 99 WHERE id = ?",
            (run.id.value,),
        )

    with pytest.raises(WorkflowDefinitionMismatch):
        reconciler.reconcile_run(WorkflowRunId("R1"))
    assert worker.calls == 0


def test_runner_state_schema_guard(tmp_path: Path) -> None:
    """check_state_schema raises on an incompatible snapshot but skips an empty one."""
    runner = build_runner(tmp_path, CountingWorker())

    runner.check_state_schema({})  # empty thread (no checkpoint) → no-op
    with pytest.raises(GraphStateSchemaMismatch):
        runner.check_state_schema({"graph_state_schema_version": 999})
