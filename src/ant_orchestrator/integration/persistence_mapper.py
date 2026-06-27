"""Durable persistence of an authoritative worker result (PHASE_5_PLAN CP6 §11/§6/§12).

After the Documentation Ant returns a verified result, this mapper persists the WorkerRun,
the ExecutionEvidence envelope, and the durable energy-settlement row in ONE SQLite unit of
work, then — only after that transaction commits — advances the mutation journal
``PUBLISHED → COMPLETED``. Every record id is deterministic, so a retry reconciles by
compare-and-verify: an identical record is an idempotent reuse, a conflicting one is a
structured fail-closed conflict (never a silent overwrite). The filesystem journal and the
SQLite records stay two durability domains; the journal is the recovery bridge.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

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
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.execution.prepared_mutation import JournalStatus, JournalStore
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.errors import (
    EnergySettlementConflict,
    EvidencePersistenceConflict,
    ReconciliationConflict,
    RecoveryInvariantViolation,
    WorkerRunPersistenceConflict,
)
from ant_orchestrator.integration.evidence_envelope import (
    EvidenceEnvelope,
    EvidenceEnvelopeError,
)
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork, UnitOfWorkRepositories

UnitOfWorkFactory = Callable[[], SqliteUnitOfWork]


@dataclass(frozen=True, slots=True)
class PersistencePlan:
    """The authoritative facts needed to persist one durable execution record set."""

    task_id: str
    run_id: str
    attempt_id: str
    logical_action_id: str
    proposal_digest: str
    succeeded: bool
    files_read: tuple[str, ...]
    files_changed: tuple[str, ...]
    commands: tuple[str, ...]
    envelope: EvidenceEnvelope
    settlement_tokens: int

    def worker_run_id(self) -> str:
        return identity.worker_run_id(
            self.run_id, self.logical_action_id, self.proposal_digest, self.attempt_id
        )

    def invocation_id(self) -> str:
        return identity.invocation_id(
            self.run_id, self.attempt_id, self.logical_action_id, self.proposal_digest
        )


@dataclass(frozen=True, slots=True)
class PersistenceOutcome:
    """The result of persisting + completing one execution record set."""

    worker_run_id: str
    evidence_id: str
    energy_settlement_id: str
    journal_completed: bool


class ExecutionPersister:
    """Persists records atomically then completes the journal (idempotent on replay)."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def persist(self, plan: PersistencePlan, journal_store: JournalStore) -> PersistenceOutcome:
        """Reconcile records in one UoW, commit, then advance the journal to COMPLETED.

        Journal status is inspected FIRST: an already-COMPLETED journal whose durable
        records are missing is an impossible state (completion only follows commit) and
        fails closed; otherwise the records are reconciled and the journal advanced.
        """
        wr_id = plan.worker_run_id()
        ev_id = identity.evidence_id(wr_id)
        eu_id = identity.energy_settlement_id(plan.invocation_id())
        outcome = PersistenceOutcome(wr_id, ev_id, eu_id, journal_completed=True)

        journal = journal_store.load()
        completed = journal.status_enum is JournalStatus.COMPLETED
        if not completed and journal.status_enum is not JournalStatus.PUBLISHED:
            raise ReconciliationConflict("journal must be PUBLISHED before completion")

        # PUBLISHED → reconcile + insert; COMPLETED → verify-only (compare-and-verify),
        # where a missing record is an impossible state and fails closed.
        now = self._clock.now()
        with self._uow_factory() as uow:
            self._reconcile_worker_run(uow, plan, wr_id, now, allow_insert=not completed)
            self._reconcile_evidence(uow, plan, wr_id, ev_id, now, allow_insert=not completed)
            self._reconcile_energy(uow, plan, wr_id, eu_id, now, allow_insert=not completed)

        if not completed:
            journal_store.save(journal.advance_to(JournalStatus.COMPLETED))
        return outcome

    # --- record reconciliation (compare-and-verify, never blind overwrite) ----
    @staticmethod
    def _missing(allow_insert: bool) -> None:
        if not allow_insert:
            raise RecoveryInvariantViolation("journal COMPLETED but a durable record is missing")

    def _reconcile_worker_run(
        self,
        uow: UnitOfWorkRepositories,
        plan: PersistencePlan,
        wr_id: str,
        now: UtcTimestamp,
        *,
        allow_insert: bool,
    ) -> None:
        status = WorkerRunStatus.SUCCEEDED if plan.succeeded else WorkerRunStatus.FAILED
        existing = uow.worker_runs.find(WorkerRunId(wr_id))
        if existing is None:
            self._missing(allow_insert)
            uow.worker_runs.add(
                WorkerRun(
                    id=WorkerRunId(wr_id),
                    task_id=TaskId(plan.task_id),
                    status=status,
                    created_at=now,
                    finished_at=now,
                )
            )
            return
        if existing.status is not status or existing.task_id.value != plan.task_id:
            raise WorkerRunPersistenceConflict("worker run identity bound a different outcome")

    def _reconcile_evidence(
        self,
        uow: UnitOfWorkRepositories,
        plan: PersistencePlan,
        wr_id: str,
        ev_id: str,
        now: UtcTimestamp,
        *,
        allow_insert: bool,
    ) -> None:
        existing = uow.evidence.find(EvidenceId(ev_id))
        if existing is None:
            self._missing(allow_insert)
            uow.evidence.add(
                ExecutionEvidence(
                    id=EvidenceId(ev_id),
                    worker_run_id=WorkerRunId(wr_id),
                    created_at=now,
                    files_read=plan.files_read,
                    files_changed=plan.files_changed,
                    commands=plan.commands,
                    result=plan.envelope.to_result_json(),
                )
            )
            return
        if (
            existing.files_read != plan.files_read
            or existing.files_changed != plan.files_changed
            or not _envelope_matches(existing.result, plan.envelope)
        ):
            raise EvidencePersistenceConflict("evidence identity bound a different envelope")

    def _reconcile_energy(
        self,
        uow: UnitOfWorkRepositories,
        plan: PersistencePlan,
        wr_id: str,
        eu_id: str,
        now: UtcTimestamp,
        *,
        allow_insert: bool,
    ) -> None:
        existing = uow.energy_usage.find(EnergyUsageId(eu_id))
        if existing is None:
            self._missing(allow_insert)
            uow.energy_usage.add(
                EnergyUsage(
                    id=EnergyUsageId(eu_id),
                    tokens_in=TokenCount(plan.settlement_tokens),
                    tokens_out=TokenCount(0),
                    created_at=now,
                    task_id=TaskId(plan.task_id),
                    worker_run_id=WorkerRunId(wr_id),
                )
            )
            return
        if existing.tokens_in.value != plan.settlement_tokens:
            raise EnergySettlementConflict("energy settlement id bound a different usage")


def _envelope_matches(stored_result: str | None, envelope: EvidenceEnvelope) -> bool:
    try:
        return EvidenceEnvelope.from_result_json(stored_result).matches(envelope)
    except EvidenceEnvelopeError:
        return False
