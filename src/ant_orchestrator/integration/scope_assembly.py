"""Assemble the immutable ApprovedExecutionScope after a valid approval (PHASE_5_PLAN CP6 §5).

The scope is built ONLY from verified authority — the approved proposal, the approval
reference, and the stable attempt id — never from a model or the semantic task. The energy
reservation reference and the idempotency key are deterministic functions of the identity
chain so a retry of the same logical execution assembles the identical scope.
"""

from __future__ import annotations

import hashlib

from ant_orchestrator.application.ports.execution_scope import (
    ApprovedExecutionScope,
    ExecutionProposal,
)


def _chain_digest(proposal: ExecutionProposal, attempt_id: str) -> str:
    parts = (
        proposal.run_id,
        proposal.logical_action_id,
        proposal.proposal_digest(),
        attempt_id,
    )
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def reservation_ref_for(proposal: ExecutionProposal, attempt_id: str) -> str:
    """Deterministic energy reservation reference bound to proposal + stable attempt."""
    return f"res:{_chain_digest(proposal, attempt_id)[:32]}"


def _idempotency_key(proposal: ExecutionProposal, attempt_id: str) -> str:
    return _chain_digest(proposal, attempt_id)


def assemble_scope(
    *,
    proposal: ExecutionProposal,
    approval_ref: str,
    proposal_ref: str,
    attempt_id: str,
    artifact_root_ref: str,
) -> ApprovedExecutionScope:
    """Build the immutable worker scope from approved authority + the stable attempt."""
    return ApprovedExecutionScope(
        attempt_id=attempt_id,
        approval_ref=approval_ref,
        proposal_ref=proposal_ref,
        proposal_digest=proposal.proposal_digest(),
        approved_target=proposal.candidate_target,
        approved_operation=proposal.operation,
        canonical_read_scope=proposal.canonical_read_scope,
        canonical_write_scope=proposal.canonical_write_scope,
        context_package_ref=proposal.context_package_ref,
        manifest_digest=proposal.manifest_digest,
        protected_policy_version=proposal.protected_policy_version,
        energy_reservation_ref=reservation_ref_for(proposal, attempt_id),
        artifact_root=artifact_root_ref,
        idempotency_key=_idempotency_key(proposal, attempt_id),
    )
