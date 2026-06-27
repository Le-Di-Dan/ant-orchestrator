"""Execution authority contracts — proposal (pre-approval) and approved scope (PHASE_5_PLAN CP1).

Phase 5 splits *intent* (``DocumentationTask``) from *authority*. The Orchestrator
builds an immutable ``ExecutionProposal`` BEFORE human approval; its
``proposal_digest`` is what the approval binds to (PF-2). Only AFTER a valid
approval and a stable execution-attempt id does the Orchestrator assemble an
immutable ``ApprovedExecutionScope`` the worker consumes (I4).

I12: ``ExecutionProposal`` carries NO ``approval_ref`` and NO ``attempt_id`` —
those values do not exist when it is built. They appear only on
``ApprovedExecutionScope``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


@dataclass(frozen=True, slots=True)
class ExecutionProposal:
    """Immutable pre-approval authority candidate (I12).

    ``candidate_target`` and the scope tuples are canonical, workspace-relative
    paths produced by the Orchestrator — never by a model. The proposal has no
    volatile fields, so ``proposal_digest`` binds exactly what approval reviews.
    """

    run_id: str
    logical_action_id: str
    task_ref: str
    candidate_target: str
    operation: DocumentOperation
    canonical_read_scope: tuple[str, ...]
    canonical_write_scope: tuple[str, ...]
    protected_policy_version: int
    context_package_ref: str
    manifest_digest: str
    energy_estimate: TokenCount
    expected_mutation: str
    proposal_version: int
    proposal_key: str

    def __post_init__(self) -> None:
        for name in (
            "run_id",
            "logical_action_id",
            "candidate_target",
            "context_package_ref",
            "manifest_digest",
            "proposal_key",
        ):
            if not getattr(self, name):
                raise InvariantViolation(f"ExecutionProposal.{name} must be non-empty")
        if self.protected_policy_version < 1:
            raise InvariantViolation("ExecutionProposal.protected_policy_version must be >= 1")
        if self.proposal_version < 1:
            raise InvariantViolation("ExecutionProposal.proposal_version must be >= 1")

    def proposal_digest(self) -> str:
        """SHA-256 over a canonical representation of the content fields.

        Deterministic and stable across processes: same content → same digest.
        """
        payload = {
            "run_id": self.run_id,
            "logical_action_id": self.logical_action_id,
            "task_ref": self.task_ref,
            "candidate_target": self.candidate_target,
            "operation": self.operation.value,
            "canonical_read_scope": list(self.canonical_read_scope),
            "canonical_write_scope": list(self.canonical_write_scope),
            "protected_policy_version": self.protected_policy_version,
            "context_package_ref": self.context_package_ref,
            "manifest_digest": self.manifest_digest,
            "energy_estimate": self.energy_estimate.value,
            "expected_mutation": self.expected_mutation,
            "proposal_version": self.proposal_version,
            "proposal_key": self.proposal_key,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ApprovedExecutionScope:
    """Immutable post-approval authority the worker consumes (I4/I12).

    Assembled ONLY after a valid approval and a stable ``attempt_id`` exist. The
    ``artifact_root`` is derived from run/attempt id and lives OUTSIDE the write
    scope (I8); ``idempotency_key`` anchors the run/action/proposal/attempt chain
    (PF-6).
    """

    attempt_id: str
    approval_ref: str
    proposal_ref: str
    proposal_digest: str
    approved_target: str
    approved_operation: DocumentOperation
    canonical_read_scope: tuple[str, ...]
    canonical_write_scope: tuple[str, ...]
    context_package_ref: str
    manifest_digest: str
    protected_policy_version: int
    energy_reservation_ref: str
    artifact_root: str
    idempotency_key: str

    def __post_init__(self) -> None:
        for name in (
            "attempt_id",
            "approval_ref",
            "proposal_ref",
            "proposal_digest",
            "approved_target",
            "context_package_ref",
            "manifest_digest",
            "energy_reservation_ref",
            "artifact_root",
            "idempotency_key",
        ):
            if not getattr(self, name):
                raise InvariantViolation(f"ApprovedExecutionScope.{name} must be non-empty")
        if self.protected_policy_version < 1:
            raise InvariantViolation("ApprovedExecutionScope.protected_policy_version must be >= 1")
