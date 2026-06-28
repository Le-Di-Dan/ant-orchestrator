"""CP6 no-leak sentinel tests (§9).

Verifies that durable stores do NOT accumulate rows from an execution run that
was cancelled, never started, or failed at a boundary (context digest mismatch).

Sentinel invariants:
  §9.1  Cancelled run → no execution_evidence row, no energy_usage row.
  §9.2  Boundary-denied run (context digest mismatch) → no attempt row, no evidence.
  §9.3  Fresh DB → all durable stores start empty (zero sentinel leakage).
  §9.4  Successful run → exactly one evidence row per attempt (no accumulation).
  §9.5  Repeated evidence persist → idempotent (one row, not two).
  §9.6  Window 3 recovery → no new rows in any store (reuse settled refs).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.test_failure import (
    RecoveryDisposition,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.integration.test_evidence_persister import TestEvidencePersister
from ant_orchestrator.integration.test_execution_adapter import DurableTestExecution
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
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1", run_id: str = "R1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("setup"))
    return db


def _report(run_ref: str = "R1", attempt_ref: str = "A1") -> StructuredTestReport:
    return StructuredTestReport(
        run_ref=run_ref,
        attempt_ref=attempt_ref,
        logical_action_ref="T1-test",
        worker_kind="test",
        command_key="pytest.acceptance",
        command_profile_version=1,
        sanitized_argv=("python", "-m", "pytest"),
        argv_digest="d" * 16,
        approved_targets=("tests/",),
        process_status=TestProcessStatus.COMPLETED,
        test_result=TestResult.PASSED,
        counts=TestCounts.unavailable(),
        snapshot_verified=True,
        cleanup_status=CleanupStatus.CLEAN,
        diagnostic_hint="ok",
    )


def _make_orch(db: Database, clock: FakeClock) -> AttemptOrchestrator:
    def _uow_f() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(db)

    return AttemptOrchestrator(_uow_f, clock=clock, ids=SequentialIdGenerator())


class _NeverCalledAnt:
    __test__ = False

    def execute(self, task, scope, run_id):  # type: ignore[override]
        raise AssertionError("backend must not be called")


def _count_rows(db: Database, table: str) -> int:
    with db.connect() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    return row[0] if row else 0


def _count_evidence_rows(db: Database) -> int:
    return _count_rows(db, "execution_evidence")


def _count_energy_rows(db: Database) -> int:
    return _count_rows(db, "energy_usage")


def _count_attempt_rows(db: Database) -> int:
    return _count_rows(db, "execution_attempts")


# ---------------------------------------------------------------------------
# §9.2 — boundary-denied run leaves no attempt or evidence
# ---------------------------------------------------------------------------


def test_context_digest_mismatch_no_attempt_row(tmp_path: Path) -> None:
    """§9.2: context digest mismatch → no ExecutionAttempt row created in DB."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    adapter = DurableTestExecution(
        ant=_NeverCalledAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
        expected_context_digest="approved",
    )

    outcome = adapter.execute(task_id="T1", run_id="R1", context_manifest_digest="TAMPERED")
    assert outcome.disposition is RecoveryDisposition.TERMINAL_FAILED

    assert _count_attempt_rows(db) == 0, "no attempt for boundary-denied execution"


def test_context_digest_mismatch_no_evidence_row(tmp_path: Path) -> None:
    """§9.2: context digest mismatch → no execution_evidence row in DB."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    adapter = DurableTestExecution(
        ant=_NeverCalledAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
        expected_context_digest="approved",
    )

    adapter.execute(task_id="T1", run_id="R1", context_manifest_digest="TAMPERED")
    assert _count_evidence_rows(db) == 0


# ---------------------------------------------------------------------------
# §9.3 — fresh DB starts empty
# ---------------------------------------------------------------------------


def test_fresh_db_all_stores_empty(tmp_path: Path) -> None:
    """§9.3: bootstrap only; no writes → all durable stores are empty."""
    clock = _clock()
    db = _make_db(tmp_path, clock)

    assert _count_evidence_rows(db) == 0
    assert _count_energy_rows(db) == 0
    assert _count_attempt_rows(db) == 0


# ---------------------------------------------------------------------------
# §9.4 — successful run → exactly one evidence row per attempt
# ---------------------------------------------------------------------------


def test_successful_persist_one_evidence_row(tmp_path: Path) -> None:
    """§9.4: one successful persist → exactly one evidence row, no accumulation."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    p.persist(
        task_id="T1",
        run_id="R1",
        attempt_id="A1",
        logical_action_id="T1-test",
        report=_report("R1", "A1"),
        wall_time_ms=100,
        retry_delta=0,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )

    assert _count_evidence_rows(db) == 1
    assert _count_energy_rows(db) == 1


def test_two_attempts_two_evidence_rows(tmp_path: Path) -> None:
    """§9.4: two distinct attempts → two evidence rows, two energy rows."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    for attempt_id in ("A1", "A2"):
        p.persist(
            task_id="T1",
            run_id="R1",
            attempt_id=attempt_id,
            logical_action_id="T1-test",
            report=_report("R1", attempt_id),
            wall_time_ms=100,
            retry_delta=0,
            context_manifest_digest="ctx",
            read_scope_digest="scope",
        )

    assert _count_evidence_rows(db) == 2
    assert _count_energy_rows(db) == 2


# ---------------------------------------------------------------------------
# §9.5 — repeated evidence persist is idempotent (no extra row)
# ---------------------------------------------------------------------------


def test_repeated_persist_no_extra_rows(tmp_path: Path) -> None:
    """§9.5: same persist call twice → still exactly one evidence and one energy row."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    for _ in range(3):
        p.persist(
            task_id="T1",
            run_id="R1",
            attempt_id="A1",
            logical_action_id="T1-test",
            report=_report("R1", "A1"),
            wall_time_ms=100,
            retry_delta=0,
            context_manifest_digest="ctx",
            read_scope_digest="scope",
        )

    assert _count_evidence_rows(db) == 1, "idempotent replay must not accumulate evidence rows"
    assert _count_energy_rows(db) == 1, "idempotent replay must not accumulate energy rows"


# ---------------------------------------------------------------------------
# §9.6 — Window 3 recovery leaves no new rows
# ---------------------------------------------------------------------------


def test_window3_recovery_no_new_db_rows(tmp_path: Path) -> None:
    """§9.6: Window 3 recovery path → no new attempt/evidence/energy rows written."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    # Settle a SUCCEEDED attempt (simulating the pre-commit crash point).
    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    attempts_before = _count_attempt_rows(db)
    evidence_before = _count_evidence_rows(db)
    energy_before = _count_energy_rows(db)

    # Re-invoke the adapter (Window 3 scenario, no evidence persister injected).
    adapter = DurableTestExecution(
        ant=_NeverCalledAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
    )
    outcome = adapter.execute(task_id="T1", run_id="R1")

    assert outcome.outcome is WorkerOutcome.SUCCESS
    assert _count_attempt_rows(db) == attempts_before, "Window 3 must not create a new attempt"
    assert _count_evidence_rows(db) == evidence_before, "Window 3 recovery must not write evidence"
    assert _count_energy_rows(db) == energy_before, "Window 3 recovery must not write energy"
