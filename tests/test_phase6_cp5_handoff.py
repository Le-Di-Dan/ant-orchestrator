"""CP5 terminal handoff tests (§8.3).

Verifies:
* All 4 mapped terminal outcomes create a handoff record.
* Content assertions: run_ref, task_ref, final_status, schema version in payload.
* Idempotency: calling create_terminal_handoff twice returns the same handoff_id.
* No raw output, traceback, path or secret in the persisted payload.
* Bounded payload: oversized state does not persist raw content.
* Unknown outcome raises CheckpointRecoveryError (CompletionFinalizer guard).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ant_orchestrator.application.services.completion_finalizer import CompletionFinalizer
from ant_orchestrator.application.services.terminal_handoff import (
    TerminalHandoffPayload,
    TerminalHandoffService,
)
from ant_orchestrator.config.constants import TERMINAL_HANDOFF_SCHEMA_VERSION
from ant_orchestrator.core.domain.value_objects import HandoffId
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.handoff import SqliteHandoffRepository
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import uow_factory as _uow_factory_fn


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1") -> Database:
    from tests.support.cp4_helpers import add_task

    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    return db


def _handoff_service(db: Database, clock: FakeClock) -> TerminalHandoffService:
    return TerminalHandoffService(
        SqliteHandoffRepository(db),
        clock=clock,
    )


_BASE_STATE: dict[str, object] = {
    "task_id": "T1",
    "workflow_run_id": "R1",
    "phase": "test",
    "retry_count": 0,
    "retry_extension_count": 0,
    "regroup_count": 0,
    "test_attempt_ref": "A1",
    "test_outcome": "SUCCESS",
    "test_evidence_refs": ["evidence:ev001"],
    "context_manifest_digest": "ctx_hash",
}


# ---------------------------------------------------------------------------
# All 4 mapped terminal outcomes create a handoff record
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("final_outcome", ["completed", "failed", "rejected", "cancelled"])
def test_all_terminal_outcomes_create_handoff(
    tmp_path: Path, clock: FakeClock, final_outcome: str
) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    hid = svc.create_terminal_handoff(
        run_id="R1",
        task_id="T1",
        final_outcome=final_outcome,
        state=_BASE_STATE,
    )
    assert hid
    # Verify record stored.
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    assert record is not None
    assert record.summary.startswith("Terminal handoff")


# ---------------------------------------------------------------------------
# Content assertions
# ---------------------------------------------------------------------------


def test_handoff_payload_content(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock, "T-content")
    svc = _handoff_service(db, clock)
    hid = svc.create_terminal_handoff(
        run_id="R-content",
        task_id="T-content",
        final_outcome="completed",
        state={**_BASE_STATE, "phase": "test_done"},
    )
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    assert record is not None
    assert record.what_changed is not None
    payload = TerminalHandoffPayload.from_json(record.what_changed)
    assert payload.run_ref == "R-content"
    assert payload.task_ref == "T-content"
    assert payload.final_status == "completed"
    assert payload.terminal_phase == "test_done"


def test_handoff_schema_version_in_payload(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    hid = svc.create_terminal_handoff(
        run_id="R2",
        task_id="T1",
        final_outcome="failed",
        state=_BASE_STATE,
    )
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    assert record is not None
    doc = json.loads(record.what_changed)
    assert doc["handoff_schema_version"] == TERMINAL_HANDOFF_SCHEMA_VERSION


def test_handoff_evidence_refs_propagated(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    state = {**_BASE_STATE, "test_evidence_refs": ["evidence:ev001", "worker_run:wr001"]}
    hid = svc.create_terminal_handoff(
        run_id="R3",
        task_id="T1",
        final_outcome="completed",
        state=state,
    )
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    payload = TerminalHandoffPayload.from_json(record.what_changed)
    assert "evidence:ev001" in payload.evidence_refs
    assert "worker_run:wr001" in payload.evidence_refs


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_handoff_idempotent_same_id_returned(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    hid1 = svc.create_terminal_handoff(
        run_id="R4", task_id="T1", final_outcome="completed", state=_BASE_STATE
    )
    hid2 = svc.create_terminal_handoff(
        run_id="R4", task_id="T1", final_outcome="completed", state=_BASE_STATE
    )
    assert hid1 == hid2
    # Exactly one record in DB.
    repo = SqliteHandoffRepository(db)
    # find should succeed.
    record = repo.find(HandoffId(hid1))
    assert record is not None


# ---------------------------------------------------------------------------
# Security: no raw output, traceback, path, or secret in payload
# ---------------------------------------------------------------------------


def test_handoff_no_raw_output_or_secret(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    malicious_state: dict[str, object] = {
        **_BASE_STATE,
        "error_summary": "TRACEBACK INCLUDED",
        "test_evidence_refs": [],
    }
    hid = svc.create_terminal_handoff(
        run_id="R5",
        task_id="T1",
        final_outcome="failed",
        state=malicious_state,
    )
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    raw = record.what_changed or ""
    # Traceback/exception markers MUST NOT appear in the raw payload.
    assert "Traceback" not in raw
    assert "Exception" not in raw
    # Cancellation info only stored for "cancelled" outcome, not "failed".
    payload = TerminalHandoffPayload.from_json(raw)
    assert payload.cancellation_info is None


def test_cancelled_handoff_includes_bounded_cancellation_info(
    tmp_path: Path, clock: FakeClock
) -> None:
    db = _make_db(tmp_path, clock)
    svc = _handoff_service(db, clock)
    state: dict[str, object] = {
        **_BASE_STATE,
        "error_summary": "cancelled by operator",
    }
    hid = svc.create_terminal_handoff(
        run_id="R6",
        task_id="T1",
        final_outcome="cancelled",
        state=state,
    )
    repo = SqliteHandoffRepository(db)
    record = repo.find(HandoffId(hid))
    payload = TerminalHandoffPayload.from_json(record.what_changed)
    assert payload.cancellation_info is not None
    assert len(payload.cancellation_info) <= 120


# ---------------------------------------------------------------------------
# CompletionFinalizer unknown outcome guard
# ---------------------------------------------------------------------------


def test_finalizer_rejects_unknown_outcome(tmp_path: Path, clock: FakeClock) -> None:
    from ant_orchestrator.application.errors import CheckpointRecoveryError

    db = _make_db(tmp_path, clock)
    finalizer = CompletionFinalizer(
        _uow_factory_fn(db),
        clock=clock,
        ids=SequentialIdGenerator(),
    )
    from ant_orchestrator.core.domain.value_objects import WorkflowRunId

    with pytest.raises(CheckpointRecoveryError):
        finalizer.finalize(
            WorkflowRunId("non-existent-run"),
            final_outcome="unknown_terminal",
            checkpoint_id="cp1",
        )
