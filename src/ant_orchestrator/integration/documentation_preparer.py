"""Off-graph, pre-approval documentation preparation (PHASE_5_PLAN CP6 §2/§3).

Before the approval interrupt, the production workflow must prepare the immutable context
package and assemble the ``ExecutionProposal`` the approval binds to. This service drives
the CP2 ``ContextPreparationService`` (real, anti-TOCTOU context) and persists the proposal
bundle via the CP6 ``ProposalStore``, returning the compact JSON-safe state fields the graph
carries (proposal ref/digest, context ref/digest) plus the action intent that makes the
decision gate require approval. The proposal/context are built ONCE here — never rebuilt
after approval — and the proposal digest is what the approval is later verified against.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from ant_orchestrator.application.ports.context_builder import ContextBudget, ContextConsumer
from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    DocumentOperation,
)
from ant_orchestrator.application.services.context_preparation import (
    ContextPreparationService,
    ProposalDraftInput,
)
from ant_orchestrator.config.constants import DEFAULT_TIMEOUT_SECONDS
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.value_objects import TokenCount
from ant_orchestrator.infrastructure.async_bridge import AsyncDependencyRunner
from ant_orchestrator.integration.proposal_store import ProposalStore

RequestFactory = Callable[[Task], "DocumentationRequest | None"]


@dataclass(frozen=True, slots=True)
class DocumentationRequest:
    """The concrete documentation action a run will execute (target/scope/inputs)."""

    logical_action_id: str
    operation: DocumentOperation
    target_document: str
    candidate_target: str
    instruction_summary: str
    required_sections: tuple[str, ...]
    approved_inputs: tuple[str, ...]
    canonical_read_scope: tuple[str, ...]
    canonical_write_scope: tuple[str, ...]
    protected_policy_version: int
    energy_estimate: int
    expected_mutation: str = "create"
    proposal_version: int = 1


@dataclass(frozen=True, slots=True)
class PreparedDocumentation:
    """The JSON-safe state fields + action intent a prepared run injects into graph state."""

    state_fields: dict[str, object]
    action_intent: dict[str, object]


class DocumentationPreparer:
    """Prepares context + proposal before approval; returns initial-state additions."""

    def __init__(
        self,
        *,
        context_service: ContextPreparationService,
        proposal_store: ProposalStore,
        consumer: ContextConsumer,
        budget: ContextBudget,
        request_factory: RequestFactory | None = None,
        runner: AsyncDependencyRunner | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._context = context_service
        self._proposals = proposal_store
        self._consumer = consumer
        self._budget = budget
        self._request_factory = request_factory
        self._runner = (
            runner if runner is not None else AsyncDependencyRunner(default_timeout=timeout)
        )
        self._timeout = timeout

    def prepare_initial_state(self, run_id: str, task: Task) -> Mapping[str, object] | None:
        """Map a task to its documentation request and prepare it (``None`` if not a doc task)."""
        if self._request_factory is None:
            return None
        request = self._request_factory(task)
        if request is None:
            return None
        prepared = self.prepare(run_id, request)
        return {**prepared.state_fields, "action_intent": prepared.action_intent}

    def prepare(self, run_id: str, request: DocumentationRequest) -> PreparedDocumentation:
        """Build + persist the proposal/context; fail closed on a scope/identity violation."""
        task = DocumentationTask(
            logical_action_id=request.logical_action_id,
            operation=request.operation,
            target_document=request.target_document,
            instruction_summary=request.instruction_summary,
            required_sections=request.required_sections,
            approved_inputs=request.approved_inputs,
        )
        draft = ProposalDraftInput(
            run_id=run_id,
            task=task,
            candidate_target=request.candidate_target,
            canonical_read_scope=request.canonical_read_scope,
            canonical_write_scope=request.canonical_write_scope,
            protected_policy_version=request.protected_policy_version,
            energy_estimate=TokenCount(request.energy_estimate),
            expected_mutation=request.expected_mutation,
            proposal_version=request.proposal_version,
            consumer=self._consumer,
            budget=self._budget,
        )
        prepared = self._runner.run(lambda: self._context.prepare(draft), timeout=self._timeout)
        stored = self._proposals.persist(run_id, request.logical_action_id, prepared.proposal, task)
        state_fields: dict[str, object] = {
            "proposal_ref": stored.proposal_ref,
            "proposal_digest": stored.proposal_digest,
            "context_package_ref": prepared.context_package_ref,
            "manifest_digest": prepared.manifest_digest,
        }
        action_intent: dict[str, object] = {
            "logical_action_id": request.logical_action_id,
            "summary": request.instruction_summary,
            "requires_significant_write": True,
            "target_paths": [request.candidate_target],
        }
        return PreparedDocumentation(state_fields=state_fields, action_intent=action_intent)
