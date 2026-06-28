"""Concrete context-source preparer (PHASE_5_PLAN CP2 / Phase 7 CP5).

Builds a context package from the EXACT approved inputs (never scans), persists it
immutably, and returns the package reference + manifest digest. A required input
that resolves outside the read scope makes the package non-dispatchable and fails
closed here — the worker never sees a partial context.

Phase 7 CP5 adds optional memory wiring: when ``memory_criteria`` is set on the
request and a ``memory_retriever`` callable is injected, records are fetched,
budget-selected, and attached to the context build request.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

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
from ant_orchestrator.application.ports.memory_context import (
    MemoryContextSelection,
    MemoryFilterManifest,
    from_memory_record,
)
from ant_orchestrator.context.estimator import TokenEstimator
from ant_orchestrator.context.memory import select_memory_for_context
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.records import MemoryRecord
from ant_orchestrator.core.domain.value_objects import TaskId

_MemoryRetriever = Callable[[MemorySearchCriteria], Sequence[MemoryRecord]]


class ContextSourcePreparerImpl:
    """Builds + persists context from approved inputs (implements the port)."""

    def __init__(
        self,
        builder: ContextPackageBuilder,
        store: ContextPackageStore,
        *,
        estimator: TokenEstimator | None = None,
        memory_retriever: _MemoryRetriever | None = None,
    ) -> None:
        self._builder = builder
        self._store = store
        self._estimator = estimator
        self._memory_retriever = memory_retriever

    async def prepare(self, request: ContextPreparationInput) -> PreparedContextRef:
        memory_selection = self._build_memory_selection(request)
        build_request = ContextBuildRequest(
            task_id=TaskId(request.logical_action_id),
            consumer=request.consumer,
            requests=tuple(
                ArtifactRequest(path=path, requirement=ArtifactRequirement.REQUIRED)
                for path in request.approved_inputs
            ),
            excluded=request.excluded,
            budget=request.budget,
            memory_selection=memory_selection,
        )
        package = await self._builder.build(build_request)
        if not package.manifest.dispatchable:
            raise ContextScopeViolation("a required approved input is outside the read scope")
        persisted = self._store.persist(request.run_id, request.logical_action_id, package)
        return PreparedContextRef(
            context_package_ref=persisted.context_package_ref,
            manifest_digest=persisted.manifest_digest,
        )

    def _build_memory_selection(
        self, request: ContextPreparationInput
    ) -> MemoryContextSelection | None:
        if request.memory_criteria is None:
            return None
        if self._memory_retriever is None:
            raise InvariantViolation("memory_criteria is set but no memory_retriever was injected")
        criteria = request.memory_criteria
        records = self._memory_retriever(criteria)
        candidates = tuple(from_memory_record(r) for r in records)

        if not candidates:
            return None

        if self._estimator is not None:
            sel = select_memory_for_context(
                candidates, request.budget.max_input_tokens, self._estimator
            )
            entries, consumed = sel.entries, sel.consumed_tokens
        else:
            entries, consumed = candidates, 0

        if not entries:
            return None

        return MemoryContextSelection(
            entries=entries,
            applied_filter=_build_filter(criteria),
            consumed_tokens=consumed,
        )


def _build_filter(criteria: MemorySearchCriteria) -> MemoryFilterManifest:
    return MemoryFilterManifest(
        task_id=criteria.task_id.value if criteria.task_id else None,
        memory_type=criteria.memory_type.value if criteria.memory_type else None,
        source=criteria.source,
        confidence=criteria.confidence.value if criteria.confidence else None,
        tags=tuple(sorted(criteria.tags)),
        include_deprecated=criteria.include_deprecated,
        resolved_limit=criteria.limit,
    )
