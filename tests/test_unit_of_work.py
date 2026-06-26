"""Unit-of-Work atomicity tests (CP1): all-or-nothing across repositories."""

from __future__ import annotations

import sqlite3

import pytest

from ant_orchestrator.core.domain.value_objects import WorkflowRunId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.support.workflow_factories import (
    make_run,
    make_task,
    make_transition,
)


def test_commit_persists_all_mutations(database: Database) -> None:
    with SqliteUnitOfWork(database) as repos:
        repos.tasks.add(make_task())
        repos.workflow_runs.add(make_run())
        repos.transitions.append(make_transition("X1"))
    with SqliteUnitOfWork(database) as repos:
        assert repos.workflow_runs.get(WorkflowRunId("R1")) is not None
        assert len(repos.transitions.list_by_run(WorkflowRunId("R1"))) == 1


def test_exception_rolls_back_everything(database: Database) -> None:
    class Boom(RuntimeError):
        pass

    with pytest.raises(Boom):
        with SqliteUnitOfWork(database) as repos:
            repos.tasks.add(make_task())
            repos.workflow_runs.add(make_run())
            repos.transitions.append(make_transition("X1"))
            raise Boom

    # Nothing from the aborted unit of work survived.
    with sqlite3.connect(str(database.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM status_transitions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_partial_failure_rolls_back_prior_mutations(database: Database) -> None:
    # Mutation A (task + run) succeeds, then mutation B violates a constraint
    # (duplicate transition operation_id+subject) -> the whole unit rolls back, so
    # the transition log is never partially written.
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as repos:
            repos.tasks.add(make_task())
            repos.workflow_runs.add(make_run())
            repos.transitions.append(make_transition("X1", operation_id="dup"))
            repos.transitions.append(make_transition("X2", operation_id="dup"))

    with sqlite3.connect(str(database.path)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM status_transitions").fetchone()[0] == 0
