"""Fake repositories for CP3 query-service tests."""

from __future__ import annotations

from collections.abc import Sequence

from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage, AuditLogQuery
from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import EnergyUsage, ExecutionEvidence, MemoryRecord
from ant_orchestrator.core.domain.value_objects import (
    EnergyUsageId,
    EvidenceId,
    MemoryId,
    TaskId,
    WorkerRunId,
)


class FakeMemoryRepository:
    def __init__(self, records: list[MemoryRecord] | None = None) -> None:
        self._records: list[MemoryRecord] = list(records or [])
        self.last_criteria: MemorySearchCriteria | None = None

    def append(self, memory: MemoryRecord) -> None:
        self._records.append(memory)

    def get(self, memory_id: MemoryId) -> MemoryRecord:
        for r in self._records:
            if r.id == memory_id:
                return r
        raise RecordNotFound(f"MemoryRecord {memory_id}")

    def deprecate(self, memory: MemoryRecord) -> None:
        pass

    def list_by_type(self, memory_type: object) -> Sequence[MemoryRecord]:
        return [r for r in self._records if r.type == memory_type]

    def search(self, criteria: MemorySearchCriteria) -> Sequence[MemoryRecord]:
        self.last_criteria = criteria
        return list(self._records)


class FakeAuditLogReader:
    def __init__(self, page: AuditLogPage | None = None) -> None:
        self._page = page or AuditLogPage(
            events=(), corrupt_count=0, files_scanned=0, has_more=False
        )
        self.last_query: AuditLogQuery | None = None
        self.called = False

    def read(self, query: AuditLogQuery) -> AuditLogPage:
        self.last_query = query
        self.called = True
        return self._page


class FakeTaskRepository:
    def __init__(self, tasks: dict | None = None) -> None:
        self._tasks: dict[str, object] = dict(tasks or {})

    def get(self, task_id: TaskId) -> object:
        if task_id.value not in self._tasks:
            raise RecordNotFound(f"Task {task_id}")
        return self._tasks[task_id.value]

    def add(self, task: object) -> None:
        pass

    def update(self, task: object) -> None:
        pass

    def list(self) -> Sequence[object]:
        return list(self._tasks.values())

    def compare_and_set_status(self, task: object, *, expected: object) -> bool:
        return False


class FakeWorkflowRunRepository:
    def __init__(self, active_run: object = None) -> None:
        self._active = active_run

    def find_active_by_task(self, task_id: TaskId) -> object | None:
        return self._active

    def get(self, run_id: object) -> object:
        raise RecordNotFound("not found")

    def add(self, run: object) -> None:
        pass

    def update(self, run: object) -> None:
        pass

    def compare_and_set_status(self, run: object, *, expected: object) -> bool:
        return False


class FakeWorkerRunRepository:
    def __init__(self, runs: list | None = None) -> None:
        self._runs: list[object] = list(runs or [])

    def get(self, worker_run_id: WorkerRunId) -> object:
        for r in self._runs:
            if r.id == worker_run_id:  # type: ignore[union-attr]
                return r
        raise RecordNotFound(f"WorkerRun {worker_run_id}")

    def add(self, run: object) -> None:
        pass

    def update(self, run: object) -> None:
        pass

    def list_by_task(self, task_id: TaskId) -> Sequence[object]:
        return [r for r in self._runs if r.task_id == task_id]  # type: ignore[union-attr]


class FakeEnergyRepository:
    def __init__(self, records: list[EnergyUsage] | None = None) -> None:
        self._records = list(records or [])

    def append(self, usage: EnergyUsage) -> None:
        self._records.append(usage)

    def get(self, usage_id: EnergyUsageId) -> EnergyUsage:
        raise RecordNotFound("not found")

    def list_by_task(self, task_id: TaskId) -> Sequence[EnergyUsage]:
        return [r for r in self._records if r.task_id == task_id]

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[EnergyUsage]:
        return [r for r in self._records if r.worker_run_id == worker_run_id]


class FakeApprovalRepository:
    def __init__(self, approvals: list | None = None) -> None:
        self._approvals: list[object] = list(approvals or [])

    def add(self, approval: object) -> None:
        pass

    def resolve(self, approval: object) -> None:
        pass

    def get(self, approval_id: object) -> object:
        raise RecordNotFound("not found")

    def list_by_task(self, task_id: TaskId) -> Sequence[object]:
        return [a for a in self._approvals if a.task_id == task_id]  # type: ignore[union-attr]

    def find_by_gate_instance(self, gate_instance_id: object) -> object | None:
        return None

    def find_pending_by_run(self, workflow_run_id: object) -> object | None:
        return None

    def resolve_with_version(self, approval: object, *, expected_version: int) -> bool:
        return False


class FakeEvidenceRepository:
    def __init__(self, evidence: list[ExecutionEvidence] | None = None) -> None:
        self._evidence = list(evidence or [])

    def append(self, evidence: ExecutionEvidence) -> None:
        pass

    def get(self, evidence_id: EvidenceId) -> ExecutionEvidence:
        raise RecordNotFound("not found")

    def list_by_worker_run(self, worker_run_id: WorkerRunId) -> Sequence[ExecutionEvidence]:
        return [e for e in self._evidence if e.worker_run_id == worker_run_id]
