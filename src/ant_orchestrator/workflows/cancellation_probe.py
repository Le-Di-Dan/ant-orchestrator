"""CancellationProbe — cooperative cancel intent check at graph boundaries (CP6).

Reads ``cancel_requested_at`` from the canonical ``WorkflowRun`` in the database at
each safe effectful boundary (before worker invocation, before persist handoff, etc.)
so the graph can detect a cancellation request without trusting stale GraphState.
"""

from __future__ import annotations

from ant_orchestrator.application.services.workflow_support import UnitOfWorkFactory
from ant_orchestrator.core.domain.value_objects import WorkflowRunId


class CancellationProbe:
    """Reads the canonical WorkflowRun at a graph boundary and reports cancel intent.

    Injected into ``build_workflow_graph`` via ``WorkflowRunner`` so each run's cancel
    flag is read from the DB, not from potentially stale graph state.
    """

    def __init__(self, uow_factory: UnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    def is_cancel_requested(self, run_id: str) -> bool:
        """Return True when the canonical WorkflowRun has a cancel intent recorded."""
        if not run_id:
            return False
        with self._uow_factory() as uow:
            run = uow.workflow_runs.get(WorkflowRunId(run_id))
            return run.cancel_requested_at is not None
