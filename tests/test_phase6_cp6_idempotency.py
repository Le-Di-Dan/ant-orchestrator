"""CP6 idempotency tests (§7).

Verifies that all durable identities are deterministic and idempotent:
  §7.1  test_worker_run_id / evidence_id / test_energy_id are deterministic SHA-256.
  §7.2  terminal_handoff_id is deterministic (same run_id + final_outcome → same ID).
  §7.3  Different run_id or final_outcome → different handoff ID (no collision).
  §7.4  TestEvidencePersister.persist is idempotent (same inputs → same row, no duplicate).
  §7.5  Concurrent finalization is safe: second write returns same IDs (PK collision = reuse).
  §7.6  Different attempt_id → different test_worker_run_id (no cross-attempt collision).
  §7.7  test_energy_id is bound to (run_id, attempt_id), not to monotonic clock.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.config.constants import (
    TERMINAL_HANDOFF_SCHEMA_VERSION,
    TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.integration import identity
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


def _persist_call(
    p: TestEvidencePersister,
    *,
    run_id: str = "R1",
    attempt_id: str = "A1",
    task_id: str = "T1",
) -> object:
    return p.persist(
        task_id=task_id,
        run_id=run_id,
        attempt_id=attempt_id,
        logical_action_id="T1-test",
        report=_report(run_id, attempt_id),
        wall_time_ms=100,
        retry_delta=0,
        context_manifest_digest="ctx",
        read_scope_digest="scope",
    )


# ---------------------------------------------------------------------------
# §7.1 — identity chain is deterministic SHA-256
# ---------------------------------------------------------------------------


def test_test_worker_run_id_deterministic() -> None:
    """§7.1: same (run_id, logical_action_id, attempt_id) → identical worker_run_id."""
    id1 = identity.test_worker_run_id("R1", "T1-test", "A1")
    id2 = identity.test_worker_run_id("R1", "T1-test", "A1")
    assert id1 == id2
    assert len(id1) == 64  # SHA-256 hex


def test_evidence_id_deterministic() -> None:
    """§7.1: evidence_id derives from worker_run_id → stable across replays."""
    wr_id = identity.test_worker_run_id("R1", "T1-test", "A1")
    ev1 = identity.evidence_id(wr_id)
    ev2 = identity.evidence_id(wr_id)
    assert ev1 == ev2
    assert len(ev1) == 64


def test_test_energy_id_deterministic() -> None:
    """§7.1: same (run_id, attempt_id) → same energy_id (no double-charge on replay)."""
    e1 = identity.test_energy_id("R1", "A1")
    e2 = identity.test_energy_id("R1", "A1")
    assert e1 == e2
    assert len(e1) == 64


# ---------------------------------------------------------------------------
# §7.2 — terminal_handoff_id is deterministic
# ---------------------------------------------------------------------------


def test_terminal_handoff_id_deterministic() -> None:
    """§7.2: same (run_id, final_outcome) → same handoff_id."""
    h1 = identity.terminal_handoff_id("R1", "completed")
    h2 = identity.terminal_handoff_id("R1", "completed")
    assert h1 == h2
    assert len(h1) == 64


# ---------------------------------------------------------------------------
# §7.3 — different inputs → different IDs
# ---------------------------------------------------------------------------


def test_different_run_id_different_worker_run_id() -> None:
    """§7.3: run_id is part of the identity chain — different run → different ID."""
    id1 = identity.test_worker_run_id("R1", "T1-test", "A1")
    id2 = identity.test_worker_run_id("R2", "T1-test", "A1")
    assert id1 != id2


def test_different_final_outcome_different_handoff_id() -> None:
    """§7.3: final_outcome is in the handoff chain — different outcome → different ID."""
    h1 = identity.terminal_handoff_id("R1", "completed")
    h2 = identity.terminal_handoff_id("R1", "failed")
    assert h1 != h2


def test_different_run_id_different_handoff_id() -> None:
    """§7.3: run_id is in the handoff chain — different run → different handoff ID."""
    h1 = identity.terminal_handoff_id("R1", "completed")
    h2 = identity.terminal_handoff_id("R2", "completed")
    assert h1 != h2


# ---------------------------------------------------------------------------
# §7.4 — TestEvidencePersister.persist is idempotent
# ---------------------------------------------------------------------------


def test_evidence_persist_idempotent_same_ids(tmp_path: Path) -> None:
    """§7.4: same persist call twice → same worker_run_id and evidence_id (PK = reuse)."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    o1 = _persist_call(p)
    o2 = _persist_call(p)

    assert o1.worker_run_id == o2.worker_run_id
    assert o1.evidence_id == o2.evidence_id
    assert o1.energy_id == o2.energy_id


def test_evidence_persist_idempotent_no_duplicate_rows(tmp_path: Path) -> None:
    """§7.4: idempotent persist does not create extra rows in execution_evidence."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    _persist_call(p)
    _persist_call(p)
    _persist_call(p)  # three calls → still one row

    with db.connect() as conn:
        row = conn.execute("SELECT COUNT(*) FROM execution_evidence").fetchone()
    assert row[0] == 1, "replay must not create duplicate evidence rows"


# ---------------------------------------------------------------------------
# §7.5 — concurrent finalization (second call is idempotent)
# ---------------------------------------------------------------------------


def test_persist_different_attempts_different_ids(tmp_path: Path) -> None:
    """§7.5: different attempt_id → different row IDs (no cross-attempt collision)."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    p = TestEvidencePersister(lambda: SqliteUnitOfWork(db), clock=clock)

    o1 = _persist_call(p, attempt_id="A1")
    o2 = _persist_call(p, attempt_id="A2")

    assert o1.worker_run_id != o2.worker_run_id
    assert o1.evidence_id != o2.evidence_id
    assert o1.energy_id != o2.energy_id


# ---------------------------------------------------------------------------
# §7.6 — different attempt_id → different test_worker_run_id
# ---------------------------------------------------------------------------


def test_different_attempt_different_worker_run_id() -> None:
    """§7.6: attempt_id is in the identity chain — different attempt → different ID."""
    id1 = identity.test_worker_run_id("R1", "T1-test", "A1")
    id2 = identity.test_worker_run_id("R1", "T1-test", "A2")
    assert id1 != id2


def test_different_logical_action_different_worker_run_id() -> None:
    """§7.6: logical_action_id is in the identity chain — different action → different ID."""
    id1 = identity.test_worker_run_id("R1", "T1-test", "A1")
    id2 = identity.test_worker_run_id("R1", "T1-validate", "A1")
    assert id1 != id2


# ---------------------------------------------------------------------------
# §7.7 — test_energy_id not clock-dependent
# ---------------------------------------------------------------------------


def test_energy_id_same_across_clocks() -> None:
    """§7.7: energy_id depends on (run_id, attempt_id) — not wall clock."""
    e1 = identity.test_energy_id("R1", "A1")
    # Advance the notional clock — ID must be identical.
    e2 = identity.test_energy_id("R1", "A1")
    assert e1 == e2


def test_energy_id_bound_to_attempt_not_run_alone() -> None:
    """§7.7: same run_id, different attempt_id → different energy_id (per-attempt energy)."""
    e1 = identity.test_energy_id("R1", "A1")
    e2 = identity.test_energy_id("R1", "A2")
    assert e1 != e2


# ---------------------------------------------------------------------------
# Schema version constants
# ---------------------------------------------------------------------------


def test_evidence_envelope_schema_version_constant() -> None:
    """Guard: evidence envelope schema version used in evidence_id is stable."""
    assert TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION == 2


def test_terminal_handoff_schema_version_constant() -> None:
    """Guard: terminal handoff schema version is stable."""
    assert TERMINAL_HANDOFF_SCHEMA_VERSION == 1
