"""Context preparation service — binds prepared context into a proposal (PHASE_5_PLAN CP2).

Off-graph, pre-approval. Drives the ``ContextSourcePreparer`` port to obtain an
immutable context reference + manifest digest, then assembles the immutable
``ExecutionProposal`` whose ``proposal_digest`` binds that manifest digest (so a
changed context yields a different proposal). Carries NO approval/attempt authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.context_builder import ContextBudget, ContextConsumer
from ant_orchestrator.application.ports.context_preparation import (
    ContextPreparationInput,
    ContextSourcePreparer,
)
from ant_orchestrator.application.ports.document_worker import DocumentationTask
from ant_orchestrator.application.ports.execution_scope import ExecutionProposal
from ant_orchestrator.core.domain.value_objects import TokenCount


@dataclass(frozen=True, slots=True)
class ProposalDraftInput:
    """Everything needed to draft a proposal except the context refs (prepared here)."""

    run_id: str
    task: DocumentationTask
    candidate_target: str
    canonical_read_scope: tuple[str, ...]
    canonical_write_scope: tuple[str, ...]
    protected_policy_version: int
    energy_estimate: TokenCount
    expected_mutation: str
    proposal_version: int
    consumer: ContextConsumer
    budget: ContextBudget
    excluded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PreparedProposal:
    """The drafted proposal plus the context refs it binds (both immutable)."""

    proposal: ExecutionProposal
    context_package_ref: str
    manifest_digest: str


class ContextPreparationService:
    """Prepares context and assembles the proposal that binds it (pre-approval)."""

    def __init__(self, preparer: ContextSourcePreparer) -> None:
        self._preparer = preparer

    async def prepare(self, request: ProposalDraftInput) -> PreparedProposal:
        prepared = await self._preparer.prepare(
            ContextPreparationInput(
                run_id=request.run_id,
                logical_action_id=request.task.logical_action_id,
                consumer=request.consumer,
                approved_inputs=request.task.approved_inputs,
                budget=request.budget,
                excluded=request.excluded,
            )
        )
        proposal = ExecutionProposal(
            run_id=request.run_id,
            logical_action_id=request.task.logical_action_id,
            task_ref=request.task.target_document,
            candidate_target=request.candidate_target,
            operation=request.task.operation,
            canonical_read_scope=request.canonical_read_scope,
            canonical_write_scope=request.canonical_write_scope,
            protected_policy_version=request.protected_policy_version,
            context_package_ref=prepared.context_package_ref,
            manifest_digest=prepared.manifest_digest,
            energy_estimate=request.energy_estimate,
            expected_mutation=request.expected_mutation,
            proposal_version=request.proposal_version,
            proposal_key=self._proposal_key(request),
        )
        return PreparedProposal(
            proposal=proposal,
            context_package_ref=prepared.context_package_ref,
            manifest_digest=prepared.manifest_digest,
        )

    @staticmethod
    def _proposal_key(request: ProposalDraftInput) -> str:
        return f"{request.run_id}:{request.task.logical_action_id}:{request.proposal_version}"
