"""CP5 evidence persistence tests — structured test evidence envelope (§8.1).

Verifies:
* TestEvidenceEnvelope: version discriminant, round-trip, size check, fail-closed.
* TestEvidencePersister: success/failure/replay idempotency/conflict detection.
* Deterministic IDs: same inputs → same IDs; different inputs → different IDs.
* No raw output, traceback, path or secret in persisted evidence.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ant_orchestrator.integration.test_evidence_envelope import (
    TestEvidenceEnvelope,
    TestEvidenceEnvelopeError,
)
from ant_orchestrator.integration.test_evidence_persister import (
    TestEvidencePersister,
    TestPersistenceOutcome,
)
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.errors import (
    EvidencePersistenceConflict,
    WorkerRunPersistenceConflict,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
)
from ant_orchestrator.workers.test.provisioning import CleanupStatus
from ant_orchestrator.workers.test.report import (
    StructuredTestReport,
    TestCounts,
    TestProcessStatus,
    TestResult,
)
from tests.conftest import FakeClock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOW = "2026-06-28T00:00:00+00:00"


def _make_db(tmp_path: Path, clock: FakeClock) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    return Database(db_path)


def _uow_factory(db: Database):
    return lambda: SqliteUnitOfWork(db)


def _report(success: bool = True) -> StructuredTestReport:
    base = dict(
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
        test_result=TestResult.PASSED if success else TestResult.FAILED,
        counts=TestCounts.unavailable(),
        snapshot_verified=True,
        cleanup_status=CleanupStatus.CLEAN,
        diagnostic_hint="ok" if success else "2 failed",
    )
    if not success:
        base.update(
            failure_category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
            reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
            transience=Transience.DETERMINISTIC,
            recovery_disposition=RecoveryDisposition.ESCALATE,
        )
    return StructuredTestReport(**base)


def _persister(db: Database, clock: FakeClock) -> TestEvidencePersister:
    return TestEvidencePersister(_uow_factory(db), clock=clock)


def _add_task(db: Database, task_id: str, clock: FakeClock) -> None:
    from tests.support.cp4_helpers import add_task

    add_task(db, task_id, clock=clock)


def _persist(
    persister: TestEvidencePersister,
    *,
    run_id: str = "R1",
    task_id: str = "T1",
    db: Database | None = None,
    clock: FakeClock | None = None,
) -> TestPersistenceOutcome:
    return persister.persist(
        task_id=task_id,
        run_id=run_id,
        attempt_id="A1",
        logical_action_id=f"{task_id}-test",
        report=_report(),
        wall_time_ms=1000,
        retry_delta=0,
        context_manifest_digest="ctx_digest",
        read_scope_digest="scope_digest",
    )


# ---------------------------------------------------------------------------
# TestEvidenceEnvelope: round-trip, version, fail-closed
# ---------------------------------------------------------------------------


def _envelope() -> TestEvidenceEnvelope:
    return TestEvidenceEnvelope(
        run_ref="R1",
        logical_action_ref="T1-test",
        attempt_ref="A1",
        worker_kind="test",
        context_manifest_digest="ctx_hash",
        read_scope_digest="scope_hash",
        report_payload={"is_success": True, "summary_line": "5 passed"},
        created_at=_NOW,
    )


def test_envelope_round_trip() -> None:
    env = _envelope()
    raw = env.to_result_json()
    doc = json.loads(raw)
    assert doc["evidence_schema_version"] == 2
    assert doc["evidence_kind"] == "test_execution"
    restored = TestEvidenceEnvelope.from_result_json(raw)
    assert restored.matches(env)


def test_envelope_version_discriminant_reject_v1() -> None:
    raw = json.dumps({"evidence_schema_version": 1, "evidence_kind": "test_execution"})
    with pytest.raises(TestEvidenceEnvelopeError):
        TestEvidenceEnvelope.from_result_json(raw)


def test_envelope_wrong_kind_rejected() -> None:
    env = _envelope()
    raw_doc = json.loads(env.to_result_json())
    raw_doc["evidence_kind"] = "documentation"
    with pytest.raises(TestEvidenceEnvelopeError):
        TestEvidenceEnvelope.from_result_json(json.dumps(raw_doc))


def test_envelope_none_rejected() -> None:
    with pytest.raises(TestEvidenceEnvelopeError):
        TestEvidenceEnvelope.from_result_json(None)


def test_envelope_no_raw_output_in_result() -> None:
    env = _envelope()
    raw = env.to_result_json()
    # Must not contain raw stdout/stderr markers
    assert "Traceback" not in raw
    assert "Exception" not in raw


def test_envelope_size_exceeded_raises(clock: FakeClock) -> None:
    oversized = "x" * 200_000
    env = TestEvidenceEnvelope(
        run_ref="R1",
        logical_action_ref="T1-test",
        attempt_ref="A1",
        worker_kind="test",
        context_manifest_digest="ctx",
        read_scope_digest="scope",
        report_payload={"oversized_data": oversized},
        created_at=_NOW,
    )
    with pytest.raises(TestEvidenceEnvelopeError):
        env.to_result_json()


# ---------------------------------------------------------------------------
# TestEvidencePersister: success path
# ---------------------------------------------------------------------------


def test_persister_success_returns_stable_ids(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    outcome = _persist(_persister(db, clock))
    assert len(outcome.worker_run_id) > 8
    assert len(outcome.evidence_id) > 8
    assert len(outcome.energy_id) > 8


def test_persister_ids_are_deterministic(tmp_path: Path, clock: FakeClock) -> None:
    dir1 = tmp_path / "db1"
    dir2 = tmp_path / "db2"
    dir1.mkdir()
    dir2.mkdir()
    db = _make_db(dir1, clock)
    _add_task(db, "T1", clock)
    p = _persister(db, clock)
    o1 = _persist(p, run_id="R1")
    # New DB — same inputs → same IDs.
    db2 = _make_db(dir2, clock)
    _add_task(db2, "T1", clock)
    p2 = _persister(db2, clock)
    o2 = _persist(p2, run_id="R1")
    assert o1.worker_run_id == o2.worker_run_id
    assert o1.evidence_id == o2.evidence_id
    assert o1.energy_id == o2.energy_id


def test_persister_different_run_id_different_ids(tmp_path: Path, clock: FakeClock) -> None:
    dir1 = tmp_path / "db1"
    dir2 = tmp_path / "db2"
    dir1.mkdir()
    dir2.mkdir()
    db = _make_db(dir1, clock)
    _add_task(db, "T1", clock)
    p = _persister(db, clock)
    o1 = _persist(p, run_id="R1")
    # New DB so no PK collision on second persist.
    db2 = _make_db(dir2, clock)
    _add_task(db2, "T1", clock)
    p2 = _persister(db2, clock)
    o2 = _persist(p2, run_id="R2")
    assert o1.worker_run_id != o2.worker_run_id
    assert o1.energy_id != o2.energy_id


# ---------------------------------------------------------------------------
# TestEvidencePersister: idempotency (replay / compare-and-verify)
# ---------------------------------------------------------------------------


def test_persister_replay_idempotent(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = _persister(db, clock)
    o1 = _persist(p)
    # Second call with same inputs: no exception, same IDs returned.
    o2 = _persist(p)
    assert o1 == o2


def test_persister_conflict_different_outcome_raises(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = _persister(db, clock)
    # First persist with a failing report.
    p.persist(
        task_id="T1",
        run_id="R1",
        attempt_id="A1",
        logical_action_id="T1-test",
        report=_report(success=False),
        wall_time_ms=999,
        retry_delta=0,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )
    # Second persist with a DIFFERENT outcome for same identity → conflict.
    with pytest.raises((WorkerRunPersistenceConflict, EvidencePersistenceConflict)):
        p.persist(
            task_id="T1",
            run_id="R1",
            attempt_id="A1",
            logical_action_id="T1-test",
            report=_report(success=True),  # different!
            wall_time_ms=999,
            retry_delta=0,
            context_manifest_digest="ctx",
            read_scope_digest="scope",
        )


# ---------------------------------------------------------------------------
# TestEvidencePersister: evidence stored in DB is retrievable
# ---------------------------------------------------------------------------


def test_persisted_evidence_readable_from_db(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    outcome = _persist(_persister(db, clock))
    from ant_orchestrator.core.domain.value_objects import EvidenceId

    with SqliteUnitOfWork(db) as uow:
        ev = uow.evidence.find(EvidenceId(outcome.evidence_id))
    assert ev is not None
    from ant_orchestrator.integration.test_evidence_envelope import TestEvidenceEnvelope

    restored = TestEvidenceEnvelope.from_result_json(ev.result)
    # run_ref = workflow run_id (not StructuredTestReport.run_ref).
    assert restored.run_ref == "R1"
    # Schema version in JSON body.
    raw_doc = json.loads(ev.result)
    assert raw_doc["evidence_schema_version"] == 2
    assert raw_doc["evidence_kind"] == "test_execution"


def test_persisted_energy_row_has_resource_amounts(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    outcome = _persist(_persister(db, clock))
    from ant_orchestrator.core.domain.value_objects import EnergyUsageId

    with SqliteUnitOfWork(db) as uow:
        eu = uow.energy_usage.find(EnergyUsageId(outcome.energy_id))
    assert eu is not None
    assert eu.resource_amounts_json is not None
    amounts = json.loads(eu.resource_amounts_json)
    assert amounts["wall_time_ms"] == 1000
    assert amounts["retries"] == 0
    assert eu.tokens_in.value == 0
    assert eu.tokens_out.value == 0
