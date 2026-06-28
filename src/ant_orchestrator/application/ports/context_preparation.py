"""Context-source preparation port (PHASE_5_PLAN CP2).

The application layer prepares context THROUGH this port so it never imports the
concrete ``context/`` builder or store. The implementation builds, digests and
persists an immutable context package and returns only JSON-safe references — the
package reference and the manifest digest — that an ``ExecutionProposal`` binds to.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.context_builder import ContextBudget, ContextConsumer
from ant_orchestrator.core.domain.query import MemorySearchCriteria


@dataclass(frozen=True, slots=True)
class ContextPreparationInput:
    """Exactly the approved inputs to prepare — never a directory to scan."""

    run_id: str
    logical_action_id: str
    consumer: ContextConsumer
    approved_inputs: tuple[str, ...]
    budget: ContextBudget
    excluded: tuple[str, ...] = ()
    memory_criteria: MemorySearchCriteria | None = None


@dataclass(frozen=True, slots=True)
class PreparedContextRef:
    """The immutable, JSON-safe references a proposal/approval binds to."""

    context_package_ref: str
    manifest_digest: str


@runtime_checkable
class ContextSourcePreparer(Protocol):
    """Builds + persists an immutable context package, returning its refs."""

    async def prepare(self, request: ContextPreparationInput) -> PreparedContextRef:
        """Prepare context off-graph, before approval; fail closed on scope failure."""
        ...
