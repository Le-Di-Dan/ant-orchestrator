"""Production workflow composition — CLI entry point (Phase 8 CP3).

Lives in ``cli/`` because it wires concrete adapter implementations
(JsonlAuditSink, JsonlAuditLogReader) which are permitted only from the
cli/adapters/api edge layers per the import boundary rules.

DeterministicStubAdapter MUST NOT appear in any code path assembled here.
Composition separation:
  - This module    → production (real LLM, fail-closed on missing config)
  - tests/support/ → test fixtures (permitted to wire stubs/fakes)
  - CP9 antctl self-test → deterministic verification mode (deferred)
"""

from __future__ import annotations

import os
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextConsumer,
)
from ant_orchestrator.application.ports.worker import WorkerActionIntent, WorkerExecutionResult
from ant_orchestrator.application.services.context_preparation import ContextPreparationService
from ant_orchestrator.application.services.search_memory import SearchMemory
from ant_orchestrator.composition import (
    SystemClock,
    Uuid4IdGenerator,
    WorkflowServices,  # noqa: F401 (re-export for callers)
    build_workflow_services,
    make_memory_retriever,
)
from ant_orchestrator.config.constants import CONFIG_FILENAME
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.loader import load_document
from ant_orchestrator.config.models import ResolvedConfig
from ant_orchestrator.config.resolver import ConfigResolver
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.execution.bounded_fs import BoundedFileSystemAdapter, BoundedFsConfig
from ant_orchestrator.integration.composition import build_documentation_execution
from ant_orchestrator.integration.documentation_preparer import DocumentationPreparer
from ant_orchestrator.integration.errors import ProductionWorkerConfigMissing
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.repositories.memory import SqliteMemoryRepository
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.discovery import find_nest
from ant_orchestrator.workspace.layout import ANT_DIRNAME, ARTIFACTS_DIRNAME, DATABASE_FILENAME

_QUEEN_REQUIRED = "models.queen must be configured for production run"
_WORKER_REQUIRED = "models.local must be configured for production run"

_DOC_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")
_DOC_BUDGET = ContextBudget(max_input_tokens=10_000, max_files=10, max_file_tokens=5_000)


class _ProductionGuardWorker:
    """Sentinel worker that raises if the fallback stub path is reached in production.

    Wired as the ``worker`` argument in :func:`build_production_workflow_services`.
    Since ``documentation_execution`` is always non-None in production, the graph
    never calls this. If it does, it is a wiring error that must surface immediately.
    """

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        raise ProductionWorkerConfigMissing(
            "Stub fallback reached in production composition — "
            "this is a wiring error; documentation_execution must be non-None"
        )


def validate_production_config(config: ResolvedConfig) -> None:
    """Fail fast if the config is missing required production provider endpoints.

    Raises :class:`ConfigInvalid` (→ exit 2) when queen or local endpoint is absent.
    """
    if config.models.queen is None:
        raise ConfigInvalid(_QUEEN_REQUIRED)
    if config.models.local is None:
        raise ConfigInvalid(_WORKER_REQUIRED)


def _load_config(ant_dir: Path) -> ResolvedConfig:
    file_data = load_document(ant_dir / CONFIG_FILENAME)
    return ConfigResolver().resolve(file_data=file_data, env=dict(os.environ))


def build_production_workflow_services(start: Path) -> WorkflowServices:
    """Assemble production workflow services from the Nest at or above ``start``.

    Validates provider config (fails closed on missing endpoints), builds real LLM
    adapters, and wires the Documentation Ant with real Context Preparation.

    Raises:
        ConfigInvalid  (→ exit 2): queen or local provider not configured.
        NestNotFound   (→ exit 3): no ``.ant/`` directory at or above ``start``.
    """
    from ant_orchestrator.adapters.env_secret_provider import EnvSecretProvider
    from ant_orchestrator.adapters.factory import build_llm_adapter
    from ant_orchestrator.adapters.litellm_client import LiteLLMSdkClient
    from ant_orchestrator.application.ports.workspace import NestNotFound
    from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer

    root = find_nest(start)
    if root is None:
        raise NestNotFound(f"No .ant/ found from {start}")

    ant_dir = root / ANT_DIRNAME
    config = _load_config(ant_dir)
    validate_production_config(config)

    clock = SystemClock()
    ids = Uuid4IdGenerator()
    artifacts_root = ant_dir / ARTIFACTS_DIRNAME
    logs_dir = ant_dir / "logs"

    # Real LLM worker adapter for Documentation Ant
    local_adapter = build_llm_adapter(
        config.models.local,  # type: ignore[arg-type]
        secret_provider=EnvSecretProvider(),
        completion_client=LiteLLMSdkClient(),
    )
    composer = LLMDocumentationComposer(local_adapter)

    database = Database(ant_dir / DATABASE_FILENAME)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(database)

    sink = JsonlAuditSink(logs_dir, clock=clock, redactor=Redactor())
    docs_root = root / "docs"

    fs = BoundedFileSystemAdapter(
        config=BoundedFsConfig(workspace_root=root),
        path_policy=PathPolicy(
            PathScope.build(read_roots=(root,), write_roots=(docs_root,)),
            workspace_root=root,
        ),
        redactor=Redactor(),
        audit_sink=sink,
        clock=clock,
        id_gen=ids,
    )
    builder = ContextPackageBuilder(
        fs=fs,
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=sink,
        clock=clock,
        id_gen=ids,
    )
    search = SearchMemory(SqliteMemoryRepository(database), sink, clock=clock, ids=ids)
    context_service = ContextPreparationService(
        ContextSourcePreparerImpl(
            builder,
            ContextPackageStore(artifacts_root),
            memory_retriever=make_memory_retriever(search),
        )
    )
    policy = ProtectedPathPolicy(
        scope=PathScope.build(read_roots=(), write_roots=(docs_root,)),
        workspace_root=root,
        policy_version=1,
    )
    doc_adapter = build_documentation_execution(
        composer=composer,
        policy=policy,
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        workspace_root=root,
        artifacts_root=artifacts_root,
    )
    preparer = DocumentationPreparer(
        context_service=context_service,
        proposal_store=ProposalStore(artifacts_root),
        consumer=_DOC_CONSUMER,
        budget=_DOC_BUDGET,
    )
    return build_workflow_services(
        start,
        worker=_ProductionGuardWorker(),
        documentation_execution=doc_adapter,
        documentation_preparer=preparer,
        audit_sink=sink,
        audit_log_reader=JsonlAuditLogReader(logs_dir),
        clock=clock,
        ids=ids,
    )
