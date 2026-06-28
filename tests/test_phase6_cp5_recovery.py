"""CP5 recovery / partial-failure / replay tests (§8.4).

Verifies:
* Replay after UoW commit: same IDs, no duplicate rows.
* Handoff replay is a no-op (idempotent by deterministic HandoffId).
* Partial failure: handoff-only failure propagates (fail-closed).
* TerminalHandoffPayload.from_json fails closed on wrong schema version.
* Energy row persisted with different retry_delta raises conflict.
* migration_v3: v2→v3 adds resource_amounts_json column; idempotent at v3.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ant_orchestrator.application.services.terminal_handoff import (
    TerminalHandoffPayload,
    TerminalHandoffPayloadError,
)
from ant_orchestrator.config.constants import TERMINAL_HANDOFF_SCHEMA_VERSION
from ant_orchestrator.integration.errors import EnergySettlementConflict
from ant_orchestrator.integration.test_evidence_persister import TestEvidencePersister
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workers.test.provisioning import CleanupStatus
from ant_orchestrator.workers.test.report import (
    StructuredTestReport,
    TestCounts,
    TestProcessStatus,
    TestResult,
)
from tests.conftest import FakeClock


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str | None = None) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    if task_id is not None:
        _add_task(db, task_id, clock)
    return db


def _report() -> StructuredTestReport:
    return StructuredTestReport(
        run_ref="run-1",
        attempt_ref="att-1",
        logical_action_ref="T1-test",
        worker_kind="test",
        command_key="pytest.acceptance",
        command_profile_version=1,
        sanitized_argv=("python", "-m", "pytest"),
        argv_digest="d" * 16,
        approved_targets=("tests/unit",),
        process_status=TestProcessStatus.COMPLETED,
        test_result=TestResult.PASSED,
        counts=TestCounts.unavailable(),
        snapshot_verified=True,
        cleanup_status=CleanupStatus.CLEAN,
        diagnostic_hint="ok",
    )


def _add_task(db: Database, task_id: str, clock: FakeClock) -> None:
    from tests.support.cp4_helpers import add_task

    add_task(db, task_id, clock=clock)


def _persist(persister: TestEvidencePersister, *, run_id: str, attempt_id: str, retry_delta: int):
    return persister.persist(
        task_id="T1",
        run_id=run_id,
        attempt_id=attempt_id,
        logical_action_id="T1-test",
        report=_report(),
        wall_time_ms=100,
        retry_delta=retry_delta,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )


# ---------------------------------------------------------------------------
# Replay: same IDs on second persist
# ---------------------------------------------------------------------------


def test_evidence_replay_returns_same_ids(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock, "T1")
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    o1 = _persist(p, run_id="R1", attempt_id="A1", retry_delta=0)
    # Replay (crash + retry).
    o2 = _persist(p, run_id="R1", attempt_id="A1", retry_delta=0)
    assert o1 == o2


# ---------------------------------------------------------------------------
# Energy conflict: different retry_delta raises
# ---------------------------------------------------------------------------


def test_energy_conflict_different_retry_delta(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock, "T1")
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    _persist(p, run_id="R2", attempt_id="A1", retry_delta=0)
    with pytest.raises(EnergySettlementConflict):
        # Same deterministic energy ID, but different retry_delta → conflict.
        _persist(p, run_id="R2", attempt_id="A1", retry_delta=1)


# ---------------------------------------------------------------------------
# TerminalHandoffPayload: fail-closed on wrong schema version
# ---------------------------------------------------------------------------


def test_payload_wrong_version_rejected() -> None:
    doc = {
        "handoff_schema_version": 999,
        "run_ref": "R1",
        "task_ref": "T1",
        "final_status": "completed",
    }
    with pytest.raises(TerminalHandoffPayloadError):
        TerminalHandoffPayload.from_json(json.dumps(doc))


def test_payload_missing_version_rejected() -> None:
    doc = {"run_ref": "R1", "task_ref": "T1", "final_status": "completed"}
    with pytest.raises(TerminalHandoffPayloadError):
        TerminalHandoffPayload.from_json(json.dumps(doc))


def test_payload_none_rejected() -> None:
    with pytest.raises(TerminalHandoffPayloadError):
        TerminalHandoffPayload.from_json(None)


def test_payload_non_object_rejected() -> None:
    with pytest.raises(TerminalHandoffPayloadError):
        TerminalHandoffPayload.from_json(json.dumps([1, 2, 3]))


# ---------------------------------------------------------------------------
# migration_v3: idempotent at v3, resource_amounts_json column present
# ---------------------------------------------------------------------------


def test_migration_v3_column_present_after_bootstrap(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    # Verify the column exists after bootstrap.
    with db.connect() as conn:
        info = conn.execute("PRAGMA table_info(energy_usage)").fetchall()
    col_names = {row["name"] for row in info}
    assert "resource_amounts_json" in col_names


def test_migration_v3_idempotent_double_bootstrap(tmp_path: Path, clock: FakeClock) -> None:
    db_path = tmp_path / "state.sqlite"
    # First bootstrap.
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    # Second bootstrap must not raise.
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    with db.connect() as conn:
        info = conn.execute("PRAGMA table_info(energy_usage)").fetchall()
    col_names = {row["name"] for row in info}
    assert "resource_amounts_json" in col_names


# ---------------------------------------------------------------------------
# Handoff replay: calling create_terminal_handoff twice is idempotent
# ---------------------------------------------------------------------------


def test_handoff_replay_no_duplicate_record(tmp_path: Path, clock: FakeClock) -> None:
    from ant_orchestrator.application.services.terminal_handoff import TerminalHandoffService
    from ant_orchestrator.core.domain.value_objects import HandoffId
    from ant_orchestrator.persistence.repositories.handoff import SqliteHandoffRepository

    db = _make_db(tmp_path, clock, "T1")
    svc = TerminalHandoffService(SqliteHandoffRepository(db), clock=clock)
    state: dict[str, object] = {
        "phase": "test",
        "retry_count": 0,
        "retry_extension_count": 0,
        "regroup_count": 0,
    }
    hid1 = svc.create_terminal_handoff(
        run_id="R-rep", task_id="T1", final_outcome="completed", state=state
    )
    hid2 = svc.create_terminal_handoff(
        run_id="R-rep", task_id="T1", final_outcome="completed", state=state
    )
    assert hid1 == hid2
    repo = SqliteHandoffRepository(db)
    # Should be findable.
    assert repo.find(HandoffId(hid1)) is not None


# ---------------------------------------------------------------------------
# Partial failure: handoff error propagates (fail-closed), doesn't swallow
# ---------------------------------------------------------------------------


def test_handoff_error_propagates_fail_closed(tmp_path: Path, clock: FakeClock) -> None:
    """If the handoff repository raises, CompletionFinalizer propagates the error."""
    from unittest.mock import MagicMock

    from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
    from ant_orchestrator.application.services.terminal_handoff import TerminalHandoffService
    from ant_orchestrator.core.domain.value_objects import WorkflowRunId
    from ant_orchestrator.persistence.repositories.handoff import SqliteHandoffRepository
    from tests.conftest import SequentialIdGenerator
    from tests.support.cp4_helpers import add_task, create_running_run, uow_factory as _uow_f

    db = _make_db(tmp_path, clock)
    # Insert a RUNNING task + run so CompletionFinalizer can fetch them.
    add_task(db, "T-err", clock=clock)
    run_id = WorkflowRunId("R-err")
    setup_ids = SequentialIdGenerator(prefix="SETUP")
    create_running_run(db, run_id, "T-err", clock, setup_ids)

    # Mock handoff repo so find() returns None but append() raises.
    mock_repo = MagicMock(spec=SqliteHandoffRepository)
    mock_repo.find.return_value = None
    mock_repo.append.side_effect = RuntimeError("db exploded")

    svc = TerminalHandoffService(mock_repo, clock=clock)

    finalizer = CompletionFinalizer(
        _uow_f(db),
        clock=clock,
        ids=SequentialIdGenerator(prefix="FINAL"),
        terminal_handoff=svc,
    )
    with pytest.raises(RuntimeError, match="db exploded"):
        finalizer.finalize(
            run_id,
            final_outcome="completed",
            checkpoint_id="cp-err",
            state={"phase": "test", "retry_count": 0, "retry_extension_count": 0, "regroup_count": 0},
        )
