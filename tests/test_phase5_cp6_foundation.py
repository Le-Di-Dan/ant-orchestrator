"""PHASE_5_PLAN CP6 foundation: deterministic identity, evidence envelope, conn repos."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import pytest

from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.core.domain.entities import WorkerRun
from ant_orchestrator.core.domain.enums import WorkerRunStatus
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    TaskId,
    TokenCount,
    UtcTimestamp,
    WorkerRunId,
)
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.evidence_envelope import (
    EvidenceEnvelope,
    EvidenceEnvelopeError,
)
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork

_NOW = UtcTimestamp(datetime(2026, 6, 27, tzinfo=UTC))


# --- definition version bump --------------------------------------------------
def test_definition_version_is_four() -> None:
    # CP4 (phase6): node ``test`` added → topology change → version 3→4.
    assert WORKFLOW_DEFINITION_VERSION == 4


# --- deterministic identity ---------------------------------------------------
def test_worker_run_id_is_deterministic_and_chain_bound() -> None:
    args = ("run", "act", "pdigest", "att")
    assert identity.worker_run_id(*args) == identity.worker_run_id(*args)
    assert identity.worker_run_id(*args) != identity.worker_run_id("run", "act", "pdigest", "att2")
    assert identity.worker_run_id(*args) != identity.worker_run_id(
        "run", "act", "pdigest", "att", "other_kind"
    )


def test_evidence_and_settlement_ids_are_deterministic() -> None:
    wr = identity.worker_run_id("run", "act", "pdigest", "att")
    assert identity.evidence_id(wr) == identity.evidence_id(wr)
    inv = identity.invocation_id("run", "att", "act", "pdigest")
    assert len(inv) == 32
    assert identity.energy_settlement_id(inv) == identity.energy_settlement_id(inv)
    assert identity.energy_settlement_id(inv) != identity.energy_settlement_id("other")


# --- evidence envelope --------------------------------------------------------
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


def test_envelope_round_trips() -> None:
    env = _envelope()
    restored = EvidenceEnvelope.from_result_json(env.to_result_json())
    assert restored == env
    assert restored.matches(env)


def test_envelope_rejects_unknown_version() -> None:
    raw = '{"evidence_schema_version": 999, "run_id": "r"}'
    with pytest.raises(EvidenceEnvelopeError):
        EvidenceEnvelope.from_result_json(raw)


def test_envelope_rejects_malformed_and_empty() -> None:
    with pytest.raises(EvidenceEnvelopeError):
        EvidenceEnvelope.from_result_json("{not json")
    with pytest.raises(EvidenceEnvelopeError):
        EvidenceEnvelope.from_result_json(None)


def test_envelope_rejects_oversized_provider_id() -> None:
    with pytest.raises(EvidenceEnvelopeError):
        EvidenceEnvelope(
            run_id="r",
            logical_action_id="a",
            attempt_id="t",
            proposal_ref="",
            proposal_digest="d",
            approval_ref="",
            context_package_ref="",
            manifest_digest="",
            protected_policy_version=1,
            permission_decision="allow",
            receipt_ref="",
            receipt_status="",
            draft_digest="",
            energy_estimate_tokens=0,
            energy_reservation_ref="",
            energy_actual_tokens=0,
            energy_fallback_used=False,
            energy_over_budget=False,
            energy_settlement_ref="",
            journal_ref="",
            journal_status="",
            target_digest="",
            validation_result="",
            adapter_provider="x" * 200,
        )


# --- connection-bound repositories share one transaction ----------------------
def _seed_task(database: Database, task_id: str) -> None:
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO tasks (id, title, status, source, priority, created_at, updated_at) "
            "VALUES (?, 'doc', 'running', 'cli', 'normal', ?, ?)",
            (task_id, _NOW.to_iso(), _NOW.to_iso()),
        )


def test_conn_repos_persist_and_find_atomically(database: Database) -> None:
    _seed_task(database, "task-1")
    wr_id = identity.worker_run_id("run", "act", "pdigest", "att")
    ev_id = identity.evidence_id(wr_id)
    eu_id = identity.energy_settlement_id(identity.invocation_id("run", "att", "act", "pdigest"))

    with SqliteUnitOfWork(database) as uow:
        uow.worker_runs.add(
            WorkerRun(
                id=WorkerRunId(wr_id),
                task_id=TaskId("task-1"),
                status=WorkerRunStatus.SUCCEEDED,
                created_at=_NOW,
            )
        )
        uow.evidence.add(
            ExecutionEvidence(
                id=EvidenceId(ev_id),
                worker_run_id=WorkerRunId(wr_id),
                created_at=_NOW,
                files_read=("a.md",),
                files_changed=("a.md",),
                result=_envelope().to_result_json(),
            )
        )
        uow.energy_usage.add(
            EnergyUsage(
                id=EnergyUsageId(eu_id),
                tokens_in=TokenCount(80),
                tokens_out=TokenCount(0),
                created_at=_NOW,
                task_id=TaskId("task-1"),
                worker_run_id=WorkerRunId(wr_id),
            )
        )

    with SqliteUnitOfWork(database) as uow:
        assert uow.worker_runs.find(WorkerRunId(wr_id)) is not None
        ev = uow.evidence.find(EvidenceId(ev_id))
        assert ev is not None
        assert EvidenceEnvelope.from_result_json(ev.result).matches(_envelope())
        assert uow.energy_usage.find(EnergyUsageId(eu_id)) is not None
        assert uow.worker_runs.find(WorkerRunId("missing")) is None


def test_duplicate_primary_key_is_the_idempotency_authority(database: Database) -> None:
    _seed_task(database, "task-2")
    wr_id = identity.worker_run_id("run", "act", "pdigest", "att")
    run = WorkerRun(
        id=WorkerRunId(wr_id),
        task_id=TaskId("task-2"),
        status=WorkerRunStatus.SUCCEEDED,
        created_at=_NOW,
    )
    with SqliteUnitOfWork(database) as uow:
        uow.worker_runs.add(run)
    with pytest.raises(sqlite3.IntegrityError):
        with SqliteUnitOfWork(database) as uow:
            uow.worker_runs.add(run)


def test_uow_rolls_back_all_records_on_error(database: Database) -> None:
    _seed_task(database, "task-3")
    wr_id = identity.worker_run_id("run3", "act", "pdigest", "att")
    with pytest.raises(RuntimeError):
        with SqliteUnitOfWork(database) as uow:
            uow.worker_runs.add(
                WorkerRun(
                    id=WorkerRunId(wr_id),
                    task_id=TaskId("task-3"),
                    status=WorkerRunStatus.SUCCEEDED,
                    created_at=_NOW,
                )
            )
            raise RuntimeError("boom")
    with SqliteUnitOfWork(database) as uow:
        assert uow.worker_runs.find(WorkerRunId(wr_id)) is None
