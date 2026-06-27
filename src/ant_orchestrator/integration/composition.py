"""Production composition for the durable documentation execution path (PHASE_5_PLAN CP6 §16).

Assembles the ``DocumentationExecutionAdapter`` from its collaborators with a durable,
provider-neutral wiring: a real ``DurableEnergyLifecycle`` (never the in-memory CP5
lifecycle), the connection-bound persistence unit of work, the protected-path policy, the
context/proposal/journal stores, and the Documentation Ant driven through an injected
provider-neutral composer. A missing composer fails closed — the production path never
falls back to a stub worker or a placeholder context.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ant_orchestrator.application.ports.documentation_composer import DocumentationComposer
from ant_orchestrator.config.constants import DEFAULT_TIMEOUT_SECONDS
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator
from ant_orchestrator.energy.durable_lifecycle import DurableEnergyLifecycle
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.integration.errors import ProductionWorkerConfigMissing
from ant_orchestrator.integration.execution_adapter import DocumentationExecutionAdapter
from ant_orchestrator.integration.persistence_mapper import ExecutionPersister
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.workers.documentation.ant import DocumentationAnt
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator

UnitOfWorkFactory = Callable[[], SqliteUnitOfWork]


def build_documentation_execution(
    *,
    composer: DocumentationComposer | None,
    policy: ProtectedPathPolicy,
    uow_factory: UnitOfWorkFactory,
    clock: Clock,
    ids: IdGenerator,
    workspace_root: Path,
    artifacts_root: Path,
    provider_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> DocumentationExecutionAdapter:
    """Assemble the production documentation execution adapter (fail-closed on missing config).

    ``composer`` is the provider-neutral seam: the CLI supplies a real LLM-backed composer
    and tests supply a deterministic fake. ``None`` means the production worker is not
    configured — a hard, fail-closed error rather than a silent stub fallback.
    """
    if composer is None:
        raise ProductionWorkerConfigMissing("documentation composer/provider is not configured")

    energy = DurableEnergyLifecycle()
    ant = DocumentationAnt(
        composer=composer,
        runner=AsyncDependencyRunner(default_timeout=provider_timeout),
        energy=energy,
        mutator=SafeDocumentMutator(
            policy=policy, workspace_root=workspace_root, artifacts_root=artifacts_root
        ),
        policy=policy,
        context_store=ContextPackageStore(artifacts_root),
        workspace_root=workspace_root,
        artifacts_root=artifacts_root,
        provider_timeout=provider_timeout,
    )
    return DocumentationExecutionAdapter(
        ant=ant,
        attempt_orchestrator=AttemptOrchestrator(uow_factory, clock=clock, ids=ids),
        energy=energy,
        persister=ExecutionPersister(uow_factory, clock=clock),
        proposal_store=ProposalStore(artifacts_root),
        artifacts_root=artifacts_root,
    )
