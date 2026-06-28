"""Durable Test Ant evidence + energy persistence in one unit of work (CP5).

After Test Ant returns a :class:`StructuredTestReport`, this persister writes three
records atomically: a ``WorkerRun`` (attempt lifecycle), an ``ExecutionEvidence``
carrying the :class:`TestEvidenceEnvelope` payload, and an ``EnergyUsage`` row with
WALL_TIME and retry-delta.  Every record id is deterministic so a replay (crash + retry)
reconciles by compare-and-verify (PK collision = same record = idempotent re-use).

The persister NEVER writes a ``StructuredTestReport`` directly to GraphState — only
opaque references (``evidence:<id>``, ``worker_run:<id>``) are returned for state use.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from ant_orchestrator.config.constants import TEST_WORKER_KIND
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
from ant_orchestrator.integration import identity
from ant_orchestrator.integration.errors import (
    EnergySettlementConflict,
    EvidencePersistenceConflict,
    WorkerRunPersistenceConflict,
)
from ant_orchestrator.integration.test_evidence_envelope import (
    TestEvidenceEnvelope,
    TestEvidenceEnvelopeError,
)
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork, UnitOfWorkRepositories
from ant_orchestrator.workers.test.report import StructuredTestReport

UnitOfWorkFactory = Callable[[], SqliteUnitOfWork]


@dataclass(frozen=True, slots=True)
class TestPersistenceOutcome:
    """IDs of the persisted records (used for state refs)."""

    worker_run_id: str
    evidence_id: str
    energy_id: str


class TestEvidencePersister:
    """Persist Test Ant evidence + energy atomically; idempotent on replay."""

    def __init__(self, uow_factory: UnitOfWorkFactory, *, clock: Clock) -> None:
        self._uow_factory = uow_factory
        self._clock = clock

    def persist(
        self,
        *,
        task_id: str,
        run_id: str,
        attempt_id: str,
        logical_action_id: str,
        report: StructuredTestReport,
        wall_time_ms: int,
        retry_delta: int,
        context_manifest_digest: str,
        read_scope_digest: str,
    ) -> TestPersistenceOutcome:
        """Persist WorkerRun + Evidence + Energy in one UoW; return stable refs.

        Idempotent: a replay with the same inputs writes nothing new (PK collision =
        compare-and-verify).  A conflicting record (different outcome) fails closed.
        """
        wr_id = identity.test_worker_run_id(run_id, logical_action_id, attempt_id)
        ev_id = identity.evidence_id(wr_id, schema_version=2)
        en_id = identity.test_energy_id(run_id, attempt_id)
        envelope = self._build_envelope(
            run_id=run_id,
            logical_action_id=logical_action_id,
            attempt_id=attempt_id,
            report=report,
            context_manifest_digest=context_manifest_digest,
            read_scope_digest=read_scope_digest,
        )
        succeeded = report.is_success
        now = self._clock.now()
        with self._uow_factory() as uow:
            self._reconcile_worker_run(uow, wr_id, task_id, succeeded, now)
            self._reconcile_evidence(uow, wr_id, ev_id, envelope, now)
            self._reconcile_energy(uow, en_id, wr_id, task_id, wall_time_ms, retry_delta, now)
        return TestPersistenceOutcome(worker_run_id=wr_id, evidence_id=ev_id, energy_id=en_id)

    # --- record builders --------------------------------------------------

    @staticmethod
    def _build_envelope(
        *,
        run_id: str,
        logical_action_id: str,
        attempt_id: str,
        report: StructuredTestReport,
        context_manifest_digest: str,
        read_scope_digest: str,
    ) -> TestEvidenceEnvelope:
        import datetime

        created_at = datetime.datetime.now(datetime.UTC).isoformat()
        return TestEvidenceEnvelope(
            run_ref=run_id,
            logical_action_ref=logical_action_id,
            attempt_ref=attempt_id,
            worker_kind=TEST_WORKER_KIND,
            context_manifest_digest=context_manifest_digest,
            read_scope_digest=read_scope_digest,
            report_payload=report.to_state_dict(),
            created_at=created_at,
        )

    # --- compare-and-verify reconciliation --------------------------------

    @staticmethod
    def _reconcile_worker_run(
        uow: UnitOfWorkRepositories,
        wr_id: str,
        task_id: str,
        succeeded: bool,
        now: UtcTimestamp,
    ) -> None:
        status = WorkerRunStatus.SUCCEEDED if succeeded else WorkerRunStatus.FAILED
        existing = uow.worker_runs.find(WorkerRunId(wr_id))
        if existing is None:
            uow.worker_runs.add(
                WorkerRun(
                    id=WorkerRunId(wr_id),
                    task_id=TaskId(task_id),
                    status=status,
                    created_at=now,
                    finished_at=now,
                )
            )
            return
        if existing.status is not status or existing.task_id.value != task_id:
            raise WorkerRunPersistenceConflict("test worker run identity bound a different outcome")

    @staticmethod
    def _reconcile_evidence(
        uow: UnitOfWorkRepositories,
        wr_id: str,
        ev_id: str,
        envelope: TestEvidenceEnvelope,
        now: UtcTimestamp,
    ) -> None:
        existing = uow.evidence.find(EvidenceId(ev_id))
        if existing is None:
            uow.evidence.add(
                ExecutionEvidence(
                    id=EvidenceId(ev_id),
                    worker_run_id=WorkerRunId(wr_id),
                    created_at=now,
                    result=envelope.to_result_json(),
                )
            )
            return
        try:
            stored = TestEvidenceEnvelope.from_result_json(existing.result)
        except TestEvidenceEnvelopeError as exc:
            raise EvidencePersistenceConflict(
                "stored test evidence is unreadable on reconciliation"
            ) from exc
        if not stored.matches(envelope):
            raise EvidencePersistenceConflict("test evidence identity bound a different envelope")

    @staticmethod
    def _reconcile_energy(
        uow: UnitOfWorkRepositories,
        en_id: str,
        wr_id: str,
        task_id: str,
        wall_time_ms: int,
        retry_delta: int,
        now: UtcTimestamp,
    ) -> None:
        existing = uow.energy_usage.find(EnergyUsageId(en_id))
        if existing is None:
            amounts = json.dumps(
                {"wall_time_ms": wall_time_ms, "retries": retry_delta},
                sort_keys=True,
                separators=(",", ":"),
            )
            uow.energy_usage.add(
                EnergyUsage(
                    id=EnergyUsageId(en_id),
                    tokens_in=TokenCount(0),
                    tokens_out=TokenCount(0),
                    created_at=now,
                    task_id=TaskId(task_id),
                    worker_run_id=WorkerRunId(wr_id),
                    resource_amounts_json=amounts,
                )
            )
            return
        stored_amounts = existing.resource_amounts_json
        expected = json.dumps(
            {"wall_time_ms": wall_time_ms, "retries": retry_delta},
            sort_keys=True,
            separators=(",", ":"),
        )
        if stored_amounts != expected:
            raise EnergySettlementConflict(
                "test energy id bound a different resource amounts record"
            )


__all__ = ["TestEvidencePersister", "TestPersistenceOutcome"]
