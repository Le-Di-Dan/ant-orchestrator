"""Dedicated self-test composition (Phase 8 CP6).

Assembles workflow services bound to a *temporary isolated* Nest using a
deterministic clock, deterministic id factory and the production
:class:`DeterministicStubAdapter` — no LLM, no Ollama, no HTTP client, no API key,
no production secret, no user project state. This composition is intentionally
separate from production ``run`` (``cli.composition_production``) and must NEVER be
reachable from the production command routing.

Lives in ``cli/`` because it wires concrete adapters (JsonlAuditSink/Reader),
which the import-boundary rules permit only from the cli/adapters/api edge layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.services.result_finalizer import TaskResultFinalizer
from ant_orchestrator.cli.self_test_artifact import SelfTestArtifactProvider
from ant_orchestrator.composition import WorkflowServices, build_workflow_services
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.task_result import SqliteTaskResultRepository
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workers.stub import DeterministicStubAdapter
from ant_orchestrator.workspace.discovery import find_nest
from ant_orchestrator.workspace.layout import (
    ANT_DIRNAME,
    ARTIFACTS_DIRNAME,
    CHECKPOINT_DB_FILENAME,
    DATABASE_FILENAME,
)

# Fixed epoch for the deterministic clock — far in the past so it can never collide
# with a real run and so audit filenames are stable across machines.
_SELF_TEST_EPOCH = datetime(2024, 1, 1, 0, 0, 0, tzinfo=UTC)


class DeterministicClock:
    """A monotonic, machine-independent clock: each ``now()`` advances one second."""

    def __init__(self) -> None:
        self._tick = 0

    def now(self) -> UtcTimestamp:
        stamp = UtcTimestamp(_SELF_TEST_EPOCH + timedelta(seconds=self._tick))
        self._tick += 1
        return stamp


class SequentialIdGenerator:
    """A deterministic id factory: ``selftest-0000``, ``selftest-0001`` …"""

    def __init__(self, prefix: str = "selftest") -> None:
        self._prefix = prefix
        self._counter = 0

    def new_id(self) -> str:
        ident = f"{self._prefix}-{self._counter:04d}"
        self._counter += 1
        return ident


@dataclass(frozen=True, slots=True)
class SelfTestComposition:
    """The deterministic services and the durable handles a self-test inspects."""

    services: WorkflowServices
    database: Database
    checkpoint_db_path: Path
    logs_dir: Path
    artifacts_root: Path
    audit_sink: JsonlAuditSink
    audit_log_reader: JsonlAuditLogReader
    redactor: Redactor
    worker: DeterministicStubAdapter


def build_self_test_services(workspace: Path) -> SelfTestComposition:
    """Assemble deterministic workflow services bound to ``workspace`` (an isolated Nest).

    The composition is offline by construction: the only worker is the no-op
    :class:`DeterministicStubAdapter`; no provider adapter, HTTP client or secret
    provider is constructed.
    """
    root = find_nest(workspace)
    if root is None:
        raise FileNotFoundError(f"No .ant/ found from {workspace}")
    ant_dir = root / ANT_DIRNAME
    logs_dir = ant_dir / "logs"
    artifacts_root = ant_dir / ARTIFACTS_DIRNAME
    checkpoint_db_path = ant_dir / CHECKPOINT_DB_FILENAME

    clock = DeterministicClock()
    ids = SequentialIdGenerator()
    redactor = Redactor()
    sink = JsonlAuditSink(logs_dir, clock=clock, redactor=redactor)
    reader = JsonlAuditLogReader(logs_dir)
    worker = DeterministicStubAdapter()

    database = Database(ant_dir / DATABASE_FILENAME)
    result_finalizer = TaskResultFinalizer(
        SqliteTaskResultRepository(database),
        clock=clock,
        artifact_provider=SelfTestArtifactProvider(artifacts_root),
    )

    services = build_workflow_services(
        workspace,
        worker=worker,
        audit_sink=sink,
        audit_log_reader=reader,
        clock=clock,
        ids=ids,
        task_result_finalizer=result_finalizer,
    )
    return SelfTestComposition(
        services=services,
        database=database,
        checkpoint_db_path=checkpoint_db_path,
        logs_dir=logs_dir,
        artifacts_root=artifacts_root,
        audit_sink=sink,
        audit_log_reader=reader,
        redactor=redactor,
        worker=worker,
    )
