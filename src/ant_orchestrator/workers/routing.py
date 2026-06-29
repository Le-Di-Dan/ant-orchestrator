"""Worker routing contract: classify a task to a WorkerKind (Phase 8 CP3).

Phase 8 MVP: all tasks default to DOCUMENTATION. Extend in later phases
when additional task types (TEST, etc.) are introduced.
"""

from __future__ import annotations

from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.enums import WorkerKind
from ant_orchestrator.core.domain.errors import DomainError


class WorkerKindUnsupported(DomainError):
    """A classified WorkerKind is not supported by this composition."""


class WorkerRouter:
    """Maps tasks to WorkerKind via deterministic rules (no LLM call).

    The routing decision is intentionally explicit and logged — never implicit.
    """

    def classify(self, task: Task) -> WorkerKind:
        """Return the WorkerKind for a task.

        Phase 8 MVP: always DOCUMENTATION. The router will be extended once
        more task types are introduced (Phase 9+).
        """
        _ = task
        return WorkerKind.DOCUMENTATION

    def assert_supported(self, kind: WorkerKind) -> None:
        """Raise WorkerKindUnsupported if ``kind`` is not handled here."""
        if kind is not WorkerKind.DOCUMENTATION:
            raise WorkerKindUnsupported(
                f"WorkerKind {kind.value!r} is not supported in this composition"
            )
