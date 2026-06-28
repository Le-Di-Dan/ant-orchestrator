"""Phase 7 CP5 — workflow memory retrieval vertical-slice integration tests.

Covers: memory records wired into context package (main), empty result when no
matching records (empty), oversized-skip budget behaviour (budget), same inputs
produce same digest (determinism), and GraphState fields are JSON-safe (graphstate).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextConsumer,
)
from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.application.services.context_preparation import ContextPreparationService
from ant_orchestrator.application.services.search_memory import SearchMemory
from ant_orchestrator.composition import make_memory_retriever
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import (
    ConfidenceLevel,
    MemoryType,
    TaskPriority,
    TaskSource,
    TaskStatus,
)
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import MemoryId, TaskId, UtcTimestamp
from ant_orchestrator.integration.documentation_preparer import (
    DocumentationPreparer,
    DocumentationRequest,
)
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.test_context_package import FakeFs

_TS = UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC))
_SOURCE = "docs/source/brief.md"
_BUDGET = ContextBudget(max_input_tokens=50_000, max_files=10, max_file_tokens=25_000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")
_EST = CharacterHeuristicEstimator(divisor=4)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_db(tmp_path: Path) -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(FakeClock(_TS)).bootstrap(db_path)
    return Database(db_path)


def _make_task(task_id: str = "T-1") -> Task:
    return Task(
        id=TaskId(task_id),
        title="integration-test-task",
        status=TaskStatus.CREATED,
        source=TaskSource.HUMAN,
        priority=TaskPriority.NORMAL,
        created_at=_TS,
        updated_at=_TS,
    )


def _seed_task(db: Database, task_id: str) -> None:
    with SqliteUnitOfWork(db) as uow:
        uow.tasks.add(_make_task(task_id))


def _seed_record(
    repo: SqliteMemoryRepository,
    mem_id: str,
    task_id: str,
    title: str = "Test Memory",
    summary: str = "A fact about the project.",
) -> MemoryRecord:
    record = MemoryRecord(
        id=MemoryId(mem_id),
        type=MemoryType.PROJECT_FACT,
        title=title,
        summary=summary,
        source="ci",
        confidence=ConfidenceLevel.HIGH,
        tags=("alpha",),
        created_at=_TS,
        task_id=TaskId(task_id),
    )
    repo.append(record)
    return record


def _build_preparer(
    tmp_path: Path, search: SearchMemory
) -> tuple[DocumentationPreparer, ContextPackageStore]:
    clock = FakeClock(_TS)
    ids = SequentialIdGenerator()
    artifacts_root = tmp_path / "artifacts"

    builder = ContextPackageBuilder(
        fs=FakeFs({_SOURCE: "brief body content"}),
        estimator=_EST,
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=clock,
        id_gen=ids,
    )
    store = ContextPackageStore(artifacts_root)
    retriever = make_memory_retriever(search)
    preparer_impl = ContextSourcePreparerImpl(
        builder, store, estimator=_EST, memory_retriever=retriever
    )
    service = ContextPreparationService(preparer_impl)
    doc_preparer = DocumentationPreparer(
        context_service=service,
        proposal_store=ProposalStore(artifacts_root),
        consumer=_CONSUMER,
        budget=_BUDGET,
    )
    return doc_preparer, store


def _request(run_id: str = "R-1", action_id: str = "act-1") -> DocumentationRequest:
    return DocumentationRequest(
        logical_action_id=action_id,
        operation=DocumentOperation.CREATE,
        target_document="handoff",
        candidate_target="docs/handoffs/HANDOFF-001.md",
        instruction_summary="write a handoff",
        required_sections=("Summary",),
        approved_inputs=(_SOURCE,),
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        protected_policy_version=1,
        energy_estimate=10_000,
    )


# ---------------------------------------------------------------------------
# Scenario 1: main path — memory records attached to context package
# ---------------------------------------------------------------------------


def test_memory_records_appear_in_context_package(tmp_path: Path) -> None:
    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-1")
    _seed_record(repo, "M-1", "T-1", title="First fact", summary="fact one")
    _seed_record(repo, "M-2", "T-1", title="Second fact", summary="fact two")

    doc_preparer, store = _build_preparer(tmp_path, search)
    prepared = doc_preparer.prepare("R-1", _request(), task_id=TaskId("T-1"))
    sf = prepared.state_fields

    sources = store.load(str(sf["context_package_ref"]), str(sf["manifest_digest"]))
    paths = {s.path for s in sources}
    assert "memory://ant/context" in paths
    mem_src = next(s for s in sources if s.path == "memory://ant/context")
    assert "First fact" in mem_src.content
    assert "Second fact" in mem_src.content


# ---------------------------------------------------------------------------
# Scenario 2: empty — no matching records → no memory source
# ---------------------------------------------------------------------------


def test_no_records_for_task_produces_no_memory_source(tmp_path: Path) -> None:
    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-OTHER")
    _seed_record(repo, "M-1", "T-OTHER", title="Other task record")

    doc_preparer, store = _build_preparer(tmp_path, search)
    prepared = doc_preparer.prepare("R-1", _request(), task_id=TaskId("T-EMPTY"))
    sf = prepared.state_fields

    sources = store.load(str(sf["context_package_ref"]), str(sf["manifest_digest"]))
    assert "memory://ant/context" not in {s.path for s in sources}


# ---------------------------------------------------------------------------
# Scenario 3: budget — oversized entry skipped, smaller included; total ≤ budget
# ---------------------------------------------------------------------------


def test_oversized_record_skipped_small_record_included(tmp_path: Path) -> None:
    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-1")
    _seed_record(repo, "M-BIG", "T-1", title="Huge", summary="x" * 20_000)
    _seed_record(repo, "M-SMALL", "T-1", title="Small fact", summary="tiny summary")

    tight_budget = ContextBudget(max_input_tokens=200, max_files=10, max_file_tokens=100)
    clock = FakeClock(_TS)
    ids2 = SequentialIdGenerator()
    builder = ContextPackageBuilder(
        fs=FakeFs({_SOURCE: "x"}),
        estimator=_EST,
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=clock,
        id_gen=ids2,
    )
    store = ContextPackageStore(tmp_path / "artifacts")
    retriever = make_memory_retriever(search)
    preparer_impl = ContextSourcePreparerImpl(
        builder, store, estimator=_EST, memory_retriever=retriever
    )
    service = ContextPreparationService(preparer_impl)
    doc_preparer = DocumentationPreparer(
        context_service=service,
        proposal_store=ProposalStore(tmp_path / "artifacts"),
        consumer=_CONSUMER,
        budget=tight_budget,
    )

    prepared = doc_preparer.prepare("R-budget", _request(), task_id=TaskId("T-1"))
    sf = prepared.state_fields

    sources = store.load(str(sf["context_package_ref"]), str(sf["manifest_digest"]))
    mem_src = next((s for s in sources if s.path == "memory://ant/context"), None)
    assert mem_src is not None, "small record should be included"
    assert "Small fact" in mem_src.content
    assert "Huge" not in mem_src.content
    mem_tokens = _EST.estimate(mem_src.content).value
    assert mem_tokens <= tight_budget.max_input_tokens


# ---------------------------------------------------------------------------
# Scenario 4: determinism — same inputs produce same digest
# ---------------------------------------------------------------------------


def test_same_task_same_records_produces_same_digest(tmp_path: Path) -> None:
    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-1")
    _seed_record(repo, "M-1", "T-1", summary="stable fact")

    doc_preparer, store = _build_preparer(tmp_path, search)
    p1 = doc_preparer.prepare("R-det", _request(action_id="det-1"), task_id=TaskId("T-1"))
    d1 = str(p1.state_fields["manifest_digest"])

    doc_preparer2, store2 = _build_preparer(tmp_path, search)
    p2 = doc_preparer2.prepare("R-det", _request(action_id="det-1"), task_id=TaskId("T-1"))
    d2 = str(p2.state_fields["manifest_digest"])

    assert d1 == d2


# ---------------------------------------------------------------------------
# Scenario 5: GraphState safety — all state fields are JSON-serialisable
# ---------------------------------------------------------------------------


def test_state_fields_are_json_safe(tmp_path: Path) -> None:
    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-1")
    _seed_record(repo, "M-1", "T-1")

    doc_preparer, _ = _build_preparer(tmp_path, search)
    prepared = doc_preparer.prepare("R-gs", _request(action_id="gs-1"), task_id=TaskId("T-1"))

    all_fields = {**prepared.state_fields, "action_intent": prepared.action_intent}
    serialized = json.dumps(all_fields)
    assert isinstance(serialized, str)
    assert "TaskId" not in serialized
    assert "UtcTimestamp" not in serialized


# ---------------------------------------------------------------------------
# Scenario 6: audit persistence — MEMORY_RETRIEVAL event emitted to real sink
# ---------------------------------------------------------------------------


def test_search_memory_emits_audit_event_to_sink(tmp_path: Path) -> None:
    from ant_orchestrator.application.ports.audit import AuditEventType

    db = _setup_db(tmp_path)
    repo = SqliteMemoryRepository(db)
    audit = FakeAuditSink()
    ids = SequentialIdGenerator()
    search = SearchMemory(repo, audit, clock=FakeClock(_TS), ids=ids)

    _seed_task(db, "T-AUD")
    _seed_record(repo, "M-AUD", "T-AUD")

    doc_preparer, _ = _build_preparer(tmp_path, search)
    doc_preparer.prepare("R-aud", _request(action_id="aud-1"), task_id=TaskId("T-AUD"))

    assert any(e.event_type is AuditEventType.MEMORY_RETRIEVAL for e in audit.events)
