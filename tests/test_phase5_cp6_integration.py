"""PHASE_5_PLAN CP6 integration: durable documentation execution adapter (E2E-ish).

Runs the real Documentation Ant (deterministic fake composer) through the production
integration adapter: proposal load + digest verify, stable attempt, durable energy,
scope assembly, worker execution, durable WorkerRun/Evidence/energy persistence, journal
completion, and attempt settlement — plus recovery idempotency (no second provider call,
no duplicate record) and fail-closed authority checks.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.application.ports.execution_scope import ExecutionProposal
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.value_objects import (
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.energy.durable_lifecycle import DurableEnergyLifecycle
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
from ant_orchestrator.execution.mutation_artifacts import ArtifactKind, ArtifactRoot
from ant_orchestrator.execution.prepared_mutation import JournalStatus, JournalStore
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.execution_adapter import DocumentationExecutionAdapter
from ant_orchestrator.integration.persistence_mapper import ExecutionPersister
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.integration.scope_assembly import assemble_scope, reservation_ref_for
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from tests.conftest import SequentialIdGenerator
from tests.test_phase5_cp5_documentation import (
    _TARGET,
    RecordingComposer,
    _artifacts,
    _draft,
    _persist_context,
    _policy,
    _result,
    _task,
)

_NOW = UtcTimestamp(datetime(2026, 6, 27, tzinfo=UTC))
_RUN = "run-1"
_ACT = "act-1"


class _Clock:
    def now(self) -> UtcTimestamp:
        return _NOW


def _proposal(ref: str, digest: str, *, estimate: int = 10000) -> ExecutionProposal:
    return ExecutionProposal(
        run_id=_RUN,
        logical_action_id=_ACT,
        task_ref="handoff",
        candidate_target=_TARGET,
        operation=DocumentOperation.CREATE,
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        protected_policy_version=1,
        context_package_ref=ref,
        manifest_digest=digest,
        energy_estimate=TokenCount(estimate),
        expected_mutation="create",
        proposal_version=1,
        proposal_key=f"{_RUN}:{_ACT}:1",
    )


def _seed_db(database: Database) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, source, priority, created_at, updated_at) "
            "VALUES ('task-1', 'doc', 'running', 'cli', 'normal', ?, ?)",
            (_NOW.to_iso(), _NOW.to_iso()),
        )
        conn.execute(
            "INSERT INTO workflow_runs (id, task_id, thread_id, status, "
            "workflow_definition_version, initial_invoke_operation_id, created_at, updated_at) "
            "VALUES (?, 'task-1', 'th', 'running', 3, 'op', ?, ?)",
            (_RUN, _NOW.to_iso(), _NOW.to_iso()),
        )


class _Harness:
    def __init__(self, tmp_path: Path, database: Database, *, estimate: int = 10000) -> None:
        self.ws = tmp_path
        ref, digest = _persist_context(tmp_path)
        self.composer = RecordingComposer(_result(_draft()))
        self.energy = DurableEnergyLifecycle()
        policy = _policy(tmp_path)
        mutator = SafeDocumentMutator(
            policy=policy, workspace_root=tmp_path, artifacts_root=_artifacts(tmp_path)
        )
        self.ant = DocumentationAnt(
            composer=self.composer,  # type: ignore[arg-type]
            runner=AsyncDependencyRunner(default_timeout=30.0),
            energy=self.energy,
            mutator=mutator,
            policy=policy,
            context_store=ContextPackageStore(_artifacts(tmp_path)),
            workspace_root=tmp_path,
            artifacts_root=_artifacts(tmp_path),
            provider_timeout=30.0,
        )
        self.proposal = _proposal(ref, digest, estimate=estimate)
        self.task = _task()
        self.pstore = ProposalStore(_artifacts(tmp_path))
        self.prepared = self.pstore.persist(_RUN, _ACT, self.proposal, self.task)
        _seed_db(database)
        uow_factory = lambda: SqliteUnitOfWork(database)  # noqa: E731
        ids = SequentialIdGenerator("ATT")
        self.attempts = AttemptOrchestrator(uow_factory, clock=_Clock(), ids=ids)
        self.persister = ExecutionPersister(uow_factory, clock=_Clock())
        self.adapter = DocumentationExecutionAdapter(
            ant=self.ant,
            attempt_orchestrator=self.attempts,
            energy=self.energy,
            persister=self.persister,
            proposal_store=self.pstore,
            artifacts_root=_artifacts(tmp_path),
        )
        self.database = database

    def execute(self, *, proposal_digest: str | None = None):  # type: ignore[no-untyped-def]
        return self.adapter.execute(
            task_id="task-1",
            run_id=_RUN,
            proposal_ref=self.prepared.proposal_ref,
            proposal_digest=proposal_digest or self.prepared.proposal_digest,
            approval_ref="approval-1",
        )

    def counts(self) -> tuple[int, int]:
        with self.database.transaction() as conn:
            wr = conn.execute("SELECT COUNT(*) c FROM worker_runs").fetchone()["c"]
            ev = conn.execute("SELECT COUNT(*) c FROM execution_evidence").fetchone()["c"]
        return wr, ev


def test_happy_path_publishes_and_persists(tmp_path: Path, database: Database) -> None:
    h = _Harness(tmp_path, database)
    outcome = h.execute()

    assert outcome.outcome is WorkerOutcome.SUCCESS
    assert h.composer.calls == 1
    assert (tmp_path / _TARGET).is_file()  # document created
    assert h.counts() == (1, 1)
    # journal COMPLETED + attempt SUCCEEDED
    roots = ArtifactRoot(_artifacts(tmp_path), _RUN, outcome.attempt_ref)
    assert JournalStore(roots.path_for(ArtifactKind.JOURNAL)).load().status_enum is (
        JournalStatus.COMPLETED
    )
    wr_id = identity.worker_run_id(_RUN, _ACT, h.prepared.proposal_digest, outcome.attempt_ref)
    with database.transaction() as conn:
        att = conn.execute("SELECT status FROM execution_attempts").fetchone()["status"]
    assert att == "succeeded"
    with SqliteUnitOfWork(database) as uow:
        assert uow.worker_runs.find(WorkerRunId(wr_id)) is not None


def test_proposal_digest_tamper_fails_closed(tmp_path: Path, database: Database) -> None:
    h = _Harness(tmp_path, database)
    outcome = h.execute(proposal_digest="deadbeef")

    assert outcome.outcome is WorkerOutcome.PERMANENT_FAILURE
    assert outcome.failure_code == "proposal_authority_invalid"
    assert h.composer.calls == 0
    assert h.counts() == (0, 0)
    assert not (tmp_path / _TARGET).exists()


def test_over_budget_does_not_publish_or_persist(tmp_path: Path, database: Database) -> None:
    h = _Harness(tmp_path, database, estimate=5)  # usage 30 > reserved 5 → over budget
    outcome = h.execute()

    assert outcome.outcome is WorkerOutcome.ESCALATION
    assert h.composer.calls == 1
    assert h.counts() == (0, 0)
    assert not (tmp_path / _TARGET).exists()


def test_recovery_window4_reuses_attempt_no_second_provider_call(
    tmp_path: Path, database: Database
) -> None:
    h = _Harness(tmp_path, database)
    # Window 4: a STARTED attempt published the target + durable receipt/journal, but the
    # attempt was never settled (crash before persistence). Pre-run the worker manually.
    attempt_id = h.attempts.before_execute(_RUN, _ACT)
    h.energy.reserve(reservation_ref_for(h.proposal, attempt_id), 10000)
    roots = ArtifactRoot(_artifacts(tmp_path), _RUN, attempt_id)
    scope = assemble_scope(
        proposal=h.proposal,
        approval_ref="approval-1",
        proposal_ref=h.prepared.proposal_ref,
        attempt_id=attempt_id,
        artifact_root_ref=roots.ref_for(ArtifactKind.JOURNAL).rsplit("/", 1)[0],
    )
    pre = h.ant.execute(h.task, scope, _RUN)
    assert pre.status.value == "published"
    assert h.composer.calls == 1

    # Recovery: the adapter reuses the same STARTED attempt — no second provider call.
    outcome = h.execute()

    assert outcome.outcome is WorkerOutcome.SUCCESS
    assert outcome.attempt_ref == attempt_id  # stable attempt reused
    assert h.composer.calls == 1  # provider NOT called again
    assert h.counts() == (1, 1)  # no duplicate records
    assert JournalStore(roots.path_for(ArtifactKind.JOURNAL)).load().status_enum is (
        JournalStatus.COMPLETED
    )
