"""CP7 E2E harness: shared helpers for the two-worker E2E scenario matrix (CP7, §2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)
from ant_orchestrator.config.constants import WORKFLOW_MAX_RETRIES
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.energy.enforcement import EnforcementPolicy
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
from ant_orchestrator.workers.test.result import TestExecutionResult
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.runner import WorkflowRunner
from ant_orchestrator.workflows.state import new_graph_state
from ant_orchestrator.workspace.layout import CHECKPOINT_DB_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

_TS = UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC))

TASK_ID = "E2E-T1"
RUN_ID = "E2E-R1"
THREAD_ID = f"wf:{RUN_ID}"
LOGICAL_ACTION_ID = f"{TASK_ID}-test"
SCOPE = ("src/",)
PROFILE_KEY = "pytest.acceptance"


class ScriptedTestPort:
    """Scripted TestExecutionPort for graph-routing E2E tests (no DB, no Docker)."""

    __test__ = False

    def __init__(self, outcomes: list[TestExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def execute(
        self, *, task_id: str, run_id: str, context_manifest_digest: str = ""
    ) -> TestExecutionOutcome:
        self.calls += 1
        return self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]


class NopRawAnt:
    """Asserts if called — proves no backend rerun in Window 3 recovery."""

    __test__ = False
    calls: int = 0

    def execute(self, task, scope, run_id):  # type: ignore[return]
        self.calls += 1
        raise AssertionError("backend must not be called in Window 3 recovery")


class FakeRawAnt:
    """Returns scripted TestExecutionResult for DurableTestExecution tests."""

    __test__ = False

    def __init__(self, outcomes: list[TestExecutionOutcome]) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    def execute(self, task, scope, run_id) -> TestExecutionResult:
        self.calls += 1
        out = self._outcomes[min(self.calls - 1, len(self._outcomes) - 1)]
        return TestExecutionResult(
            structured_report=minimal_report(scope.attempt_id, run_id, out),
            worker_report=None,
            outcome=out,
        )


def minimal_report(
    attempt_id: str, run_id: str, outcome: TestExecutionOutcome | None = None
) -> StructuredTestReport:
    """Build a minimal StructuredTestReport suitable for DurableTestExecution tests."""
    result = (
        TestResult.PASSED
        if (outcome is None or outcome.outcome is WorkerOutcome.SUCCESS)
        else TestResult.FAILED
    )
    return StructuredTestReport(
        run_ref=run_id,
        attempt_ref=attempt_id,
        logical_action_ref=LOGICAL_ACTION_ID,
        worker_kind="test",
        command_key=PROFILE_KEY,
        command_profile_version=1,
        sanitized_argv=("python", "-m", "pytest"),
        argv_digest="a" * 16,
        approved_targets=("tests/",),
        process_status=TestProcessStatus.COMPLETED,
        test_result=result,
        counts=TestCounts.unavailable(),
        snapshot_verified=True,
        cleanup_status=CleanupStatus.CLEAN,
        diagnostic_hint="ok",
    )


class _FakeWorker:
    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        return WorkerExecutionResult(outcome=WorkerOutcome.SUCCESS, detail="stub")


def fake_clock() -> FakeClock:
    return FakeClock(_TS)


def e2e_state(
    run_id: str = RUN_ID, *, base_retry_limit: int = WORKFLOW_MAX_RETRIES
) -> dict[str, object]:
    """Build a minimal valid initial graph state for E2E runner tests."""
    return dict(
        new_graph_state(task_id=TASK_ID, workflow_run_id=run_id, base_retry_limit=base_retry_limit)
    )


def make_runner(
    tmp_path: Path,
    *,
    test_execution: object = None,
    attempt_orchestrator: object = None,
    cancellation_probe: object = None,
) -> WorkflowRunner:
    """Build WorkflowRunner with optional test_execution port injected."""
    return WorkflowRunner(
        worker=_FakeWorker(),
        policy=DecisionGatePolicy(EnforcementPolicy()),
        checkpoint_db_path=tmp_path / CHECKPOINT_DB_FILENAME,
        test_execution=test_execution,  # type: ignore[arg-type]
        attempt_orchestrator=attempt_orchestrator,  # type: ignore[arg-type]
        cancellation_probe=cancellation_probe,  # type: ignore[arg-type]
    )


def make_db(
    tmp_path: Path,
    c: FakeClock,
    task_id: str = TASK_ID,
    run_id: str = RUN_ID,
) -> Database:
    """Bootstrap a SQLite state DB with one task and one running workflow run."""
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(c).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, task_id, clock=c)
    create_running_run(db, WorkflowRunId(run_id), task_id, c, SequentialIdGenerator("setup"))
    return db


def make_orch(db: Database, c: FakeClock) -> AttemptOrchestrator:
    """Build an AttemptOrchestrator over the given DB."""
    return AttemptOrchestrator(lambda: SqliteUnitOfWork(db), clock=c, ids=SequentialIdGenerator())
