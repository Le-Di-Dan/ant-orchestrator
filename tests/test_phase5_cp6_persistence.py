"""PHASE_5_PLAN CP6 durable persistence mapper: reconcile + journal completion."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.config.constants import JOURNAL_SCHEMA_VERSION
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.execution.prepared_mutation import (
    JournalStatus,
    JournalStore,
    MutationJournal,
)
from ant_orchestrator.integration.errors import (
    EnergySettlementConflict,
    WorkerRunPersistenceConflict,
)
from ant_orchestrator.integration.evidence_envelope import EvidenceEnvelope
from ant_orchestrator.integration.persistence_mapper import (
    ExecutionPersister,
    PersistencePlan,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork

_NOW = UtcTimestamp(datetime(2026, 6, 27, tzinfo=UTC))


class _Clock:
    def now(self) -> UtcTimestamp:
        return _NOW


def _seed_task(database: Database, task_id: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, source, priority, created_at, updated_at) "
            "VALUES (?, 'doc', 'running', 'cli', 'normal', ?, ?)",
            (task_id, _NOW.to_iso(), _NOW.to_iso()),
        )


def _envelope() -> EvidenceEnvelope:
    return EvidenceEnvelope(
        run_id="run",
        logical_action_id="act",
        attempt_id="att",
        proposal_ref="prop/ref",
        proposal_digest="pdigest",
        approval_ref="appr",
        context_package_ref="ctx/ref",
        manifest_digest="mdigest",
        protected_policy_version=1,
        permission_decision="allow",
        receipt_ref="receipt/ref",
        receipt_status="energy_settled",
        draft_digest="ddigest",
        energy_estimate_tokens=100,
        energy_reservation_ref="res",
        energy_actual_tokens=80,
        energy_fallback_used=False,
        energy_over_budget=False,
        energy_settlement_ref="settle",
        journal_ref="journal/ref",
        journal_status="published",
        target_digest="tdigest",
        validation_result="pass",
    )


def _plan(task_id: str = "task-1", *, succeeded: bool = True, tokens: int = 80) -> PersistencePlan:
    return PersistencePlan(
        task_id=task_id,
        run_id="run",
        attempt_id="att",
        logical_action_id="act",
        proposal_digest="pdigest",
        succeeded=succeeded,
        files_read=("ctx.md",),
        files_changed=("docs/out.md",),
        commands=(),
        envelope=_envelope(),
        settlement_tokens=tokens,
    )


def _published_journal() -> MutationJournal:
    return MutationJournal(
        schema_version=JOURNAL_SCHEMA_VERSION,
        run_id="run",
        attempt_id="att",
        logical_action_id="act",
        proposal_digest="pdigest",
        approval_ref="appr",
        context_digest="mdigest",
        canonical_target="docs/out.md",
        operation="create",
        protected_policy_version=1,
        before_kind="absent",
        previous_digest=None,
        proposed_digest="tdigest",
        before_ref="b/ref",
        before_digest="bd",
        proposed_ref="p/ref",
        proposed_digest_ref="pd",
        diff_ref="d/ref",
        diff_digest="dd",
        validation_ok=True,
        status=JournalStatus.PUBLISHED.value,
        revision=1,
    )


def _journal_store(tmp_path: Path) -> JournalStore:
    store = JournalStore(tmp_path / "journal.json")
    store.save(_published_journal())
    return store


def test_persist_writes_records_and_completes_journal(tmp_path: Path, database: Database) -> None:
    _seed_task(database, "task-1")
    persister = ExecutionPersister(lambda: SqliteUnitOfWork(database), clock=_Clock())
    store = _journal_store(tmp_path)

    outcome = persister.persist(_plan(), store)

    assert outcome.journal_completed
    assert store.load().status_enum is JournalStatus.COMPLETED
    with SqliteUnitOfWork(database) as uow:
        assert uow.worker_runs.find(WorkerRunId(outcome.worker_run_id)) is not None
        assert uow.evidence.find(EvidenceId(outcome.evidence_id)) is not None
        assert uow.energy_usage.find(EnergyUsageId(outcome.energy_settlement_id)) is not None


def test_persist_is_idempotent_on_replay(tmp_path: Path, database: Database) -> None:
    _seed_task(database, "task-1")
    persister = ExecutionPersister(lambda: SqliteUnitOfWork(database), clock=_Clock())
    store = _journal_store(tmp_path)

    first = persister.persist(_plan(), store)
    second = persister.persist(_plan(), store)  # replay: COMPLETED journal + same ids

    assert first == second
    with SqliteUnitOfWork(database) as uow:
        # exactly one row each — no duplicates
        rows = uow.energy_usage.find(EnergyUsageId(first.energy_settlement_id))
        assert rows is not None


def test_conflicting_outcome_fails_closed(tmp_path: Path, database: Database) -> None:
    _seed_task(database, "task-1")
    persister = ExecutionPersister(lambda: SqliteUnitOfWork(database), clock=_Clock())
    store = _journal_store(tmp_path)
    persister.persist(_plan(succeeded=True), store)

    with pytest.raises(WorkerRunPersistenceConflict):
        persister.persist(_plan(succeeded=False), store)


def test_conflicting_energy_fails_closed(tmp_path: Path, database: Database) -> None:
    _seed_task(database, "task-1")
    persister = ExecutionPersister(lambda: SqliteUnitOfWork(database), clock=_Clock())
    store = _journal_store(tmp_path)
    persister.persist(_plan(tokens=80), store)

    with pytest.raises(EnergySettlementConflict):
        persister.persist(_plan(tokens=999), store)
