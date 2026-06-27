"""Graph-facing documentation execution port (PHASE_5_PLAN CP6).

The workflow graph stays provider-neutral and persistence-free: it depends only on this
port, not on the Documentation Ant, the LLM adapter, or the database. A concrete
implementation (the integration layer) loads the bound proposal, assembles the approved
scope, runs the worker, persists durable records, completes the journal, and settles the
attempt — returning ONLY a compact, JSON-safe outcome the graph can fold into its state.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.entities import Task


@dataclass(frozen=True, slots=True)
class DocumentationExecutionOutcome:
    """Compact, JSON-safe result of a durable documentation execution.

    Carries no raw prompt/output/exception — only a bounded outcome, sanitized evidence
    references, the stable attempt id, and a sanitized failure code on a controlled path.
    """

    outcome: WorkerOutcome
    attempt_ref: str
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)
    failure_code: str | None = None
    provider_invoked: bool = False


@runtime_checkable
class DocumentationExecutionPort(Protocol):
    """Run one durable documentation execution for an approved, bound proposal."""

    def execute(
        self,
        *,
        task_id: str,
        run_id: str,
        proposal_ref: str,
        proposal_digest: str,
        approval_ref: str,
    ) -> DocumentationExecutionOutcome:
        """Execute (or idempotently recover) the bound documentation action."""
        ...


@runtime_checkable
class WorkflowDocumentationPreparer(Protocol):
    """Off-graph, pre-approval preparation of the context + proposal for a run.

    Returns the JSON-safe initial-state additions (proposal/context refs + digests and the
    action intent) the workflow seeds before the approval interrupt, or ``None`` when the
    task is not a documentation action (legacy/Phase-4 runs are unaffected).
    """

    def prepare_initial_state(self, run_id: str, task: Task) -> Mapping[str, object] | None:
        """Prepare + persist the proposal/context; return initial-state additions or None."""
        ...
