"""Shared helpers for the CP7 CLI command tests (test-only).

Provides a Typer ``CliRunner``, an initialized-workspace fixture, and a seeder that
drives a task to AWAITING_APPROVAL by writing real state + checkpoint rows into the
workspace databases (the production stub worker never pauses on its own, so an
interrupt runner is used to create the paused state the CLI then operates on).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.main import app
from ant_orchestrator.cli.workflow_composition import build_workflow_services
from ant_orchestrator.core.domain.enums import ApprovalStatus, ResumeOperationStatus
from ant_orchestrator.core.domain.value_objects import (
    ApprovalId,
    ResumeOperationId,
    UtcTimestamp,
    WorkflowRunId,
)
from ant_orchestrator.core.domain.workflow import ResumeOperation
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import (
    add_task,
    build_services,
    create_running_run,
    make_interrupt_runner,
)
from tests.support.workflow_runtime import CountingWorker

cli = CliRunner()


@pytest.fixture
def nest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a Nest in ``tmp_path``, chdir into it; return the root.

    Monkeypatches ``_run_services`` (used only by ``ant run``) with a test
    composition using ``CountingWorker`` — a test double, NOT DeterministicStubAdapter.
    All other commands (create/approve/reject/cancel/status) use the neutral
    composition unchanged so that approve/reject/cancel resume paths remain
    compatible with the stub-seeded state from ``seed_awaiting``.
    """
    monkeypatch.chdir(tmp_path)
    def _test_run_services(path: Path | None) -> object:
        return build_workflow_services(
            path if path is not None else Path.cwd(), worker=CountingWorker()
        )

    monkeypatch.setattr(
        "ant_orchestrator.cli.phase4_commands._run_services",
        _test_run_services,
    )
    result = cli.invoke(app, ["init"])
    assert result.exit_code == 0, result.stdout
    return tmp_path


def state_db(root: Path) -> Database:
    """Open the workspace state database for direct assertions/seeding."""
    return Database(root / ANT_DIRNAME / DATABASE_FILENAME)


def count_rows(root: Path, table: str) -> int:
    """Return the row count of ``table`` in the workspace state database."""
    with sqlite3.connect(str(root / ANT_DIRNAME / DATABASE_FILENAME)) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def seed_awaiting(root: Path, task_id: str = "T1") -> tuple[CountingWorker, str, str]:
    """Drive ``task_id`` to AWAITING_APPROVAL on the workspace databases.

    Uses an interrupt runner pointed at the same ``.ant/`` state and checkpoint files
    the CLI composition opens, so a subsequent ``ant approve/reject/cancel`` resumes
    the very checkpoint written here. Returns the worker (for call-count assertions),
    the workflow run id and the pending approval id.
    """
    db = state_db(root)
    clock = FakeClock(UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC)))
    ids = SequentialIdGenerator()
    worker = CountingWorker()
    run_svc, *_ = build_services(db, make_interrupt_runner(root / ANT_DIRNAME, worker), clock, ids)
    add_task(db, task_id, clock=clock)
    outcome = run_svc.execute(task_id)
    assert outcome.status == "waiting_for_approval"
    assert outcome.approval_id is not None
    return worker, outcome.run_id, outcome.approval_id


def seed_owned_resume(root: Path, run_id: str, approval_id: str, decision: ApprovalStatus) -> None:
    """Insert an OWNED ResumeOperation for ``approval_id`` with a given decision.

    Simulates another actor holding the resume lease with a specific decision so a CLI
    command issuing a *different* decision hits ``ApprovalStateConflict`` (exit 5).
    """
    db = state_db(root)
    now = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))
    op = ResumeOperation(
        id=ResumeOperationId("seeded-resume-op"),
        workflow_run_id=WorkflowRunId(run_id),
        approval_id=ApprovalId(approval_id),
        decision=decision,
        status=ResumeOperationStatus.OWNED,
        created_at=now,
        owner_token="other-owner",
    )
    with SqliteUnitOfWork(db) as uow:
        uow.resume_operations.add(op)


def seed_running(root: Path, task_id: str = "T1", run_id: str = "R1") -> str:
    """Insert a CREATED task plus a RUNNING workflow run (no checkpoint). Returns run id."""
    db = state_db(root)
    clock = FakeClock(UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC)))
    ids = SequentialIdGenerator()
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, ids)
    return run_id
