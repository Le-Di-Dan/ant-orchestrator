"""Concrete context-source preparer (PHASE_5_PLAN CP2).

Builds a context package from the EXACT approved inputs (never scans), persists it
immutably, and returns the package reference + manifest digest. A required input
that resolves outside the read scope makes the package non-dispatchable and fails
closed here — the worker never sees a partial context.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ContextBuildRequest,
    ContextScopeViolation,
)
from ant_orchestrator.application.ports.context_preparation import (
    ContextPreparationInput,
    PreparedContextRef,
)
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.value_objects import TaskId


class ContextSourcePreparerImpl:
    """Builds + persists context from approved inputs (implements the port)."""

    def __init__(self, builder: ContextPackageBuilder, store: ContextPackageStore) -> None:
        self._builder = builder
        self._store = store

    async def prepare(self, request: ContextPreparationInput) -> PreparedContextRef:
        build_request = ContextBuildRequest(
            task_id=TaskId(request.logical_action_id),
            consumer=request.consumer,
            requests=tuple(
                ArtifactRequest(path=path, requirement=ArtifactRequirement.REQUIRED)
                for path in request.approved_inputs
            ),
            excluded=request.excluded,
            budget=request.budget,
        )
        package = await self._builder.build(build_request)
        if not package.manifest.dispatchable:
            raise ContextScopeViolation("a required approved input is outside the read scope")
        persisted = self._store.persist(request.run_id, request.logical_action_id, package)
        return PreparedContextRef(
            context_package_ref=persisted.context_package_ref,
            manifest_digest=persisted.manifest_digest,
        )
