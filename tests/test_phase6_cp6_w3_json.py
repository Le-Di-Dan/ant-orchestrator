"""CP6 Window 3 — compact JSON corruption, round-trip, and regression (§6.6-§6.8)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.enums import ExecutionAttemptStatus
from ant_orchestrator.core.domain.test_failure import (
    FailureCategory,
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.test_execution_adapter import (
    DurableTestExecution,
    _from_compact_json,
    _to_compact_json,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


def _make_db(tmp_path: Path, clock: FakeClock, task_id: str = "T1", run_id: str = "R1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=clock)
    create_running_run(db, WorkflowRunId(run_id), task_id, clock, SequentialIdGenerator("setup"))
    return db


def _make_orch(db: Database, clock: FakeClock) -> AttemptOrchestrator:
    def _uow_f() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(db)

    return AttemptOrchestrator(_uow_f, clock=clock, ids=SequentialIdGenerator())


def _count_rows(db: Database, table: str) -> int:
    with db.connect() as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
    return row[0] if row else 0


class _NopAnt:
    __test__ = False
    calls: int = 0

    def execute(self, task, scope, run_id):  # type: ignore[override]
        self.calls += 1
        raise AssertionError("backend must not be called in Window 3 recovery")


def _failed_outcome(
    reason_code: TestReasonCode = TestReasonCode.DETERMINISTIC_TEST_FAILURE,
    category: FailureCategory = FailureCategory.DETERMINISTIC_TEST_FAILURE,
    disposition: RecoveryDisposition = RecoveryDisposition.TERMINAL_FAILED,
    worker_outcome: WorkerOutcome = WorkerOutcome.PERMANENT_FAILURE,
    attempt_ref: str = "att-1",
) -> TestExecutionOutcome:
    return TestExecutionOutcome(
        outcome=worker_outcome,
        attempt_ref=attempt_ref,
        disposition=disposition,
        reason_code=reason_code,
        category=category,
    )


def _transient_outcome(attempt_ref: str = "att-1") -> TestExecutionOutcome:
    return _failed_outcome(
        reason_code=TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED,
        category=FailureCategory.TRANSIENT_INTERRUPTION,
        disposition=RecoveryDisposition.RETRY,
        worker_outcome=WorkerOutcome.RETRYABLE_FAILURE,
        attempt_ref=attempt_ref,
    )


# ---------------------------------------------------------------------------
# §6.6 — missing/corrupt compact JSON → fail closed
# ---------------------------------------------------------------------------


def test_w3_null_compact_json_failed_escalates(tmp_path: Path) -> None:
    """§6.6: FAILED attempt with null outcome JSON → fail closed as ESCALATION."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    attempt_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(attempt_id, WorkerOutcome.PERMANENT_FAILURE)  # no compact_json

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    recovered = adapter.execute(task_id="T1", run_id="R1")

    assert ant.calls == 0
    assert _count_rows(db, "execution_attempts") == 1
    assert recovered.outcome is WorkerOutcome.ESCALATION
    assert recovered.disposition is RecoveryDisposition.ESCALATE
    assert recovered.reason_code is TestReasonCode.UNKNOWN_FAILURE


def test_w3_corrupt_compact_json_escalates(tmp_path: Path) -> None:
    """§6.6: corrupt JSON in outcome column → fail closed as ESCALATION."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    attempt_id = orch.before_execute("R1", "T1-test")
    with SqliteUnitOfWork(db) as uow:
        from ant_orchestrator.core.domain.value_objects import ExecutionAttemptId

        a = uow.execution_attempts.get(ExecutionAttemptId(attempt_id))
        uow.execution_attempts.update(
            a.with_status(
                ExecutionAttemptStatus.FAILED,
                outcome="{not valid json[",
            )
        )

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    recovered = adapter.execute(task_id="T1", run_id="R1")

    assert ant.calls == 0
    assert _count_rows(db, "execution_attempts") == 1
    assert recovered.outcome is WorkerOutcome.ESCALATION


def test_w3_wrong_version_json_escalates(tmp_path: Path) -> None:
    """§6.6: JSON with unsupported version → fail closed as ESCALATION."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    attempt_id = orch.before_execute("R1", "T1-test")
    with SqliteUnitOfWork(db) as uow:
        from ant_orchestrator.core.domain.value_objects import ExecutionAttemptId

        a = uow.execution_attempts.get(ExecutionAttemptId(attempt_id))
        uow.execution_attempts.update(
            a.with_status(
                ExecutionAttemptStatus.FAILED,
                outcome=json.dumps({"v": 999, "outcome": "permanent_failure"}),
            )
        )

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    recovered = adapter.execute(task_id="T1", run_id="R1")

    assert ant.calls == 0
    assert recovered.outcome is WorkerOutcome.ESCALATION


# ---------------------------------------------------------------------------
# §6.7 — compact JSON round-trip (serialization correctness)
# ---------------------------------------------------------------------------


def test_compact_json_round_trip_transient() -> None:
    """§6.7: _to_compact_json / _from_compact_json are inverse for RETRYABLE."""
    original = _transient_outcome("att-99")
    json_str = _to_compact_json(original)
    restored = _from_compact_json(json_str, "att-99", ("worker_run:x", "evidence:y"))
    assert restored is not None
    assert restored.outcome is WorkerOutcome.RETRYABLE_FAILURE
    assert restored.disposition is RecoveryDisposition.RETRY
    assert restored.reason_code is TestReasonCode.TRANSIENT_INTERRUPTION_AUDITED
    assert restored.category is FailureCategory.TRANSIENT_INTERRUPTION


def test_compact_json_round_trip_permanent() -> None:
    """§6.7: round-trip for PERMANENT_FAILURE."""
    original = _failed_outcome(attempt_ref="att-p")
    json_str = _to_compact_json(original)
    restored = _from_compact_json(json_str, "att-p", ())
    assert restored is not None
    assert restored.outcome is WorkerOutcome.PERMANENT_FAILURE
    assert restored.disposition is RecoveryDisposition.TERMINAL_FAILED


def test_compact_json_evidence_refs_reinjected() -> None:
    """§6.7: evidence_refs are NOT stored in JSON but are re-injected on deserialization."""
    original = _transient_outcome("att-x")
    json_str = _to_compact_json(original)
    d = json.loads(json_str)
    assert "evidence_refs" not in d  # never stored

    refs = ("worker_run:wr1", "evidence:ev1")
    restored = _from_compact_json(json_str, "att-x", refs)
    assert restored is not None
    assert restored.evidence_refs == refs


# ---------------------------------------------------------------------------
# §6.8 — regression: SUCCEEDED still recovered without backend rerun
# ---------------------------------------------------------------------------


def test_w3_succeeded_regression_no_backend_rerun(tmp_path: Path) -> None:
    """§6.8: SUCCEEDED recovery is not broken by the FAILED correction."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    ant = _NopAnt()
    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    recovered = adapter.execute(task_id="T1", run_id="R1")

    assert ant.calls == 0
    assert recovered.outcome is WorkerOutcome.SUCCESS
    assert recovered.attempt_ref == original_id
    assert _count_rows(db, "execution_attempts") == 1


def test_w3_succeeded_evidence_refs_deterministic(tmp_path: Path) -> None:
    """§6.8: SUCCEEDED recovery re-derives evidence refs from identity chain."""
    clock = _clock()
    db = _make_db(tmp_path, clock)
    orch = _make_orch(db, clock)

    original_id = orch.before_execute("R1", "T1-test")
    orch.after_execute(original_id, WorkerOutcome.SUCCESS)

    adapter = DurableTestExecution(
        ant=_NopAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest",
    )
    recovered = adapter.execute(task_id="T1", run_id="R1")

    expected_wr = identity.test_worker_run_id("R1", "T1-test", original_id)
    expected_ev = identity.evidence_id(expected_wr)
    assert f"worker_run:{expected_wr}" in recovered.evidence_refs
    assert f"evidence:{expected_ev}" in recovered.evidence_refs
