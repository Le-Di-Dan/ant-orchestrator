"""CP5 energy delta accounting tests (§8.2).

Verifies:
* Initial attempt (attempt_no=1) → RETRIES=0.
* First retry (attempt_no=2) → RETRIES=1.
* 3-attempt sequence: sum(RETRIES) == 2.
* tokens_in and tokens_out are always 0 for Test Ant rows.
* Wall time is bounded (non-negative integer).
* resource_amounts_json is parseable JSON with expected keys.
"""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
    Transience,
)
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


def _make_db(tmp_path: Path, clock: FakeClock) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    return Database(db_path)


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
        diagnostic_hint="ok" if success else "failed",
    )
    if not success:
        base.update(
            failure_category=FailureCategory.DETERMINISTIC_TEST_FAILURE,
            reason_code=TestReasonCode.DETERMINISTIC_TEST_FAILURE,
            transience=Transience.DETERMINISTIC,
            recovery_disposition=RecoveryDisposition.ESCALATE,
        )
    return StructuredTestReport(**base)


def _add_task(db: Database, task_id: str, clock: FakeClock) -> None:
    from tests.support.cp4_helpers import add_task

    add_task(db, task_id, clock=clock)


def _persist_attempt(
    persister: TestEvidencePersister,
    *,
    run_id: str,
    attempt_id: str,
    retry_delta: int,
    wall_time_ms: int = 500,
    success: bool = True,
    task_id: str = "T1",
):
    return persister.persist(
        task_id=task_id,
        run_id=run_id,
        attempt_id=attempt_id,
        logical_action_id=f"{task_id}-test",
        report=_report(success=success),
        wall_time_ms=wall_time_ms,
        retry_delta=retry_delta,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )


def _read_energy(db: Database, energy_id: str):
    from ant_orchestrator.core.domain.value_objects import EnergyUsageId

    with SqliteUnitOfWork(db) as uow:
        return uow.energy_usage.find(EnergyUsageId(energy_id))


# ---------------------------------------------------------------------------
# RETRIES=0 for initial attempt
# ---------------------------------------------------------------------------


def test_initial_attempt_retries_zero(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    outcome = _persist_attempt(p, run_id="R1", attempt_id="A1", retry_delta=0)
    eu = _read_energy(db, outcome.energy_id)
    assert eu is not None
    amounts = json.loads(eu.resource_amounts_json)
    assert amounts["retries"] == 0


# ---------------------------------------------------------------------------
# RETRIES=1 for first retry (attempt_no=2)
# ---------------------------------------------------------------------------


def test_first_retry_retries_one(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    # First attempt: retry_delta=0
    _persist_attempt(p, run_id="R2", attempt_id="A1", retry_delta=0, success=False)
    # Second attempt: retry_delta=1
    outcome2 = _persist_attempt(p, run_id="R2", attempt_id="A2", retry_delta=1)
    eu = _read_energy(db, outcome2.energy_id)
    assert eu is not None
    amounts = json.loads(eu.resource_amounts_json)
    assert amounts["retries"] == 1


# ---------------------------------------------------------------------------
# 3-attempt sequence: sum(RETRIES) == 2
# ---------------------------------------------------------------------------


def test_three_attempt_sum_retries_equals_two(tmp_path: Path, clock: FakeClock) -> None:
    # attempt 1: RETRIES=0; attempt 2: RETRIES=1; attempt 3: RETRIES=1 (delta, not cumulative)
    # sum = 0+1+1 = 2 = retry_count
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    o1 = _persist_attempt(p, run_id="R3", attempt_id="A1", retry_delta=0, success=False)
    o2 = _persist_attempt(p, run_id="R3", attempt_id="A2", retry_delta=1, success=False)
    o3 = _persist_attempt(p, run_id="R3", attempt_id="A3", retry_delta=1)  # delta=1, not 2
    total_retries = 0
    for eid in (o1.energy_id, o2.energy_id, o3.energy_id):
        eu = _read_energy(db, eid)
        assert eu is not None
        total_retries += json.loads(eu.resource_amounts_json)["retries"]
    assert total_retries == 2


# ---------------------------------------------------------------------------
# tokens_in and tokens_out are always 0
# ---------------------------------------------------------------------------


def test_tokens_always_zero(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    outcome = _persist_attempt(p, run_id="R4", attempt_id="A1", retry_delta=0)
    eu = _read_energy(db, outcome.energy_id)
    assert eu is not None
    assert eu.tokens_in.value == 0
    assert eu.tokens_out.value == 0


# ---------------------------------------------------------------------------
# wall_time_ms is non-negative
# ---------------------------------------------------------------------------


def test_wall_time_is_non_negative(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    outcome = _persist_attempt(p, run_id="R5", attempt_id="A1", retry_delta=0, wall_time_ms=750)
    eu = _read_energy(db, outcome.energy_id)
    assert eu is not None
    amounts = json.loads(eu.resource_amounts_json)
    assert amounts["wall_time_ms"] == 750
    assert amounts["wall_time_ms"] >= 0


# ---------------------------------------------------------------------------
# resource_amounts_json is valid JSON with required keys
# ---------------------------------------------------------------------------


def test_resource_amounts_json_keys(tmp_path: Path, clock: FakeClock) -> None:
    db = _make_db(tmp_path, clock)
    _add_task(db, "T1", clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    outcome = _persist_attempt(p, run_id="R6", attempt_id="A1", retry_delta=0)
    eu = _read_energy(db, outcome.energy_id)
    assert eu is not None
    amounts = json.loads(eu.resource_amounts_json)
    assert "wall_time_ms" in amounts
    assert "retries" in amounts
    # No unexpected keys
    assert set(amounts.keys()) == {"wall_time_ms", "retries"}
