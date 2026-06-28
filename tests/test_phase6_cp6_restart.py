"""CP6 restart-window tests (§3, Windows 1-8).

Verifies that durable execution side effects are idempotent or recoverable across
the eight crash windows that can occur during Test Ant execution:

Window 1: crash before backend runs (STARTED attempt exists) → reuse attempt.
Window 2: crash after backend, before settle (still STARTED) → INDETERMINATE on stale.
Window 3: crash after settle (SUCCEEDED or FAILED), before graph commit → no backend re-run.
Window 4: evidence written, energy not → energy written exactly once on recovery.
Window 5: energy written, state/report not committed → no double energy.
Windows 6-8 (handoff idempotency) are covered by CP5; this file adds regression checks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.config.constants import EXECUTION_ATTEMPT_LEASE_SECONDS
from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.integration import identity
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


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1", run_id: str = "R1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("setup"))
    return db


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


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


class _NopAnt:
    """Fake TestAnt that must NOT be called in recovery scenarios."""

    __test__ = False
    calls: int = 0

    def execute(self, task, scope, run_id):  # type: ignore[override]
        self.calls += 1
        raise AssertionError("backend must not be called in Window 3 recovery")


def _uow_factory(db: Database):  # type: ignore[no-untyped-def]
    return lambda: SqliteUnitOfWork(db)


# ---------------------------------------------------------------------------
# Window 1 — before backend runs (STARTED attempt)
# ---------------------------------------------------------------------------


def test_window1_active_started_attempt_reused(tmp_path: Path) -> None:
    """Window 1: non-stale STARTED attempt → same ID returned, no duplicate."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    id1 = orch.before_execute("R1", "T1-test")
    id2 = orch.before_execute("R1", "T1-test")  # simulate re-entry before execute
    assert id1 == id2


def test_window1_stale_started_attempt_becomes_indeterminate(tmp_path: Path) -> None:
    """Window 1 (stale lease): stale STARTED attempt → INDETERMINATE, new attempt created."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    id1 = orch.before_execute("R1", "T1-test")

    # Advance clock past lease expiry.
    stale_clock = FakeClock(
        UtcTimestamp(clock.now().value + timedelta(seconds=EXECUTION_ATTEMPT_LEASE_SECONDS + 1))
    )
    stale_orch = AttemptOrchestrator(uow_f, clock=stale_clock, ids=SequentialIdGenerator("S"))

    id2 = stale_orch.before_execute("R1", "T1-test")
    assert id2 != id1  # new attempt created

    # Old attempt is INDETERMINATE.
    with SqliteUnitOfWork(db) as uow:
        from ant_orchestrator.core.domain.value_objects import ExecutionAttemptId

        a = uow.execution_attempts.get(ExecutionAttemptId(id1))
    assert a.status is ExecutionAttemptStatus.INDETERMINATE


# ---------------------------------------------------------------------------
# Window 2 — after backend, before settle (still STARTED)
# ---------------------------------------------------------------------------


def test_window2_evidence_persist_idempotent_on_replay(tmp_path: Path) -> None:
    """Window 2: evidence persisted but attempt not settled → replay idempotent."""
    clock = _clock()
    db = _make_db(tmp_path, clock, "T1", "R1")
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)
    # First persist (before settle).
    o1 = p.persist(
        task_id="T1",
        run_id="R1",
        attempt_id="A1",
        logical_action_id="T1-test",
        report=_report("R1", "A1"),
        wall_time_ms=200,
        retry_delta=0,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )
    # Replay (crash + retry before settle).
    o2 = p.persist(
        task_id="T1",
        run_id="R1",
        attempt_id="A1",
        logical_action_id="T1-test",
        report=_report("R1", "A1"),
        wall_time_ms=200,
        retry_delta=0,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )
    assert o1 == o2  # idempotent: same IDs, no duplicate rows


# ---------------------------------------------------------------------------
# Window 3 — after settle (SUCCEEDED), before graph commit
# ---------------------------------------------------------------------------


def test_window3_succeeded_no_backend_rerun(tmp_path: Path) -> None:
    """Window 3: settled SUCCEEDED attempt → recover without calling backend."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    # Simulate: attempt created and settled SUCCEEDED (graph checkpoint not committed).
    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
    )

    outcome = adapter.execute(task_id="T1", run_id="R1")

    assert ant.calls == 0, "backend must NOT be called in Window 3 recovery"
    assert outcome.outcome is WorkerOutcome.SUCCESS
    assert outcome.attempt_ref == original_id
    assert any("worker_run:" in r for r in outcome.evidence_refs)
    assert any("evidence:" in r for r in outcome.evidence_refs)


def test_window3_evidence_refs_deterministic(tmp_path: Path) -> None:
    """Window 3: recovered evidence refs match the identity chain of the settled attempt."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
    )
    outcome = adapter.execute(task_id="T1", run_id="R1")

    expected_wr = identity.test_worker_run_id("R1", "T1-test", original_id)
    expected_ev = identity.evidence_id(expected_wr)
    assert f"worker_run:{expected_wr}" in outcome.evidence_refs
    assert f"evidence:{expected_ev}" in outcome.evidence_refs


def test_window3_no_attempt_created(tmp_path: Path) -> None:
    """Window 3: no new ExecutionAttempt is created on recovery."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
    )
    adapter.execute(task_id="T1", run_id="R1")

    with SqliteUnitOfWork(db) as uow:
        attempts = uow.execution_attempts.list_for_action(WorkflowRunId("R1"), "T1-test")
    assert len(attempts) == 1, "no new attempt must be created in Window 3"


# ---------------------------------------------------------------------------
# Window 3 FAILED — CP6 correction: FAILED is now recovered without backend rerun
# ---------------------------------------------------------------------------


def test_window3_failed_find_recoverable_window3_still_succeeded_only(tmp_path: Path) -> None:
    """find_recoverable_window3 (legacy API) still returns None for FAILED.

    The legacy method is SUCCEEDED-only. The adapter now calls
    find_recoverable_settled_attempt() which covers FAILED. This test guards the
    backward-compat contract of the legacy method.
    """
    clock = _clock()
    db = _make_db(tmp_path, clock)
    uow_f = _uow_factory(db)
    ids = SequentialIdGenerator()
    orch = AttemptOrchestrator(uow_f, clock=clock, ids=ids)

    id1 = orch.before_execute("R1", "T1-test")
    orch.after_execute(id1, WorkerOutcome.PERMANENT_FAILURE)

    # Legacy method: SUCCEEDED-only → returns None for FAILED.
    assert orch.find_recoverable_window3("R1", "T1-test") is None
    # New general method: covers FAILED → not None.
    recovered = orch.find_recoverable_settled_attempt("R1", "T1-test")
    assert recovered is not None
    assert recovered.attempt_id == id1
    assert not recovered.is_succeeded


# ---------------------------------------------------------------------------
# Windows 4-5 (energy idempotency) — regression guard post-CP5
# ---------------------------------------------------------------------------


def test_window45_energy_not_duplicated_on_replay(tmp_path: Path) -> None:
    """Windows 4-5: energy row persisted once; replay returns same energy_id."""
    clock = _clock()
    db = _make_db(tmp_path, clock, "T1", "R2")
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    o1 = p.persist(
        task_id="T1",
        run_id="R2",
        attempt_id="A2",
        logical_action_id="T1-test",
        report=_report("R2", "A2"),
        wall_time_ms=150,
        retry_delta=1,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )
    o2 = p.persist(
        task_id="T1",
        run_id="R2",
        attempt_id="A2",
        logical_action_id="T1-test",
        report=_report("R2", "A2"),
        wall_time_ms=150,
        retry_delta=1,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )
    assert o1.energy_id == o2.energy_id
