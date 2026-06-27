"""Structured integration failures for the durable documentation path (PHASE_5_PLAN CP6).

These are controlled, fail-closed errors raised when an authority/identity/digest does
not line up during proposal binding, scope assembly, persistence reconciliation, or
recovery. They never carry a raw prompt, raw provider output, or a raw exception — only a
sanitized message — so a structured failure can be surfaced into graph state safely.
"""

from __future__ import annotations

from ant_orchestrator.core.domain.errors import DomainError


class IntegrationError(DomainError):
    """Base class for CP6 durable-integration failures (fail-closed)."""


class ProposalAuthorityError(IntegrationError):
    """A persisted proposal is missing, corrupt, or its digest does not match."""


class ApprovalBindingMismatch(IntegrationError):
    """An approval does not bind the proposal/target/scope it is being resumed against."""


class ScopeAssemblyError(IntegrationError):
    """An ``ApprovedExecutionScope`` could not be assembled from verified authority."""


class ContextAuthorityMissing(IntegrationError):
    """A Phase 5 production run reached execution without a verified context/proposal."""


class ProductionWorkerConfigMissing(IntegrationError):
    """The production composition is missing the documentation worker/provider config."""


class WorkerReportInvalid(IntegrationError):
    """A worker result/report failed verification before persistence."""


class PersistenceConflict(IntegrationError):
    """A durable record exists under the same identity but with different canonical facts."""


class WorkerRunPersistenceConflict(PersistenceConflict):
    """A WorkerRun row exists with a conflicting outcome/identity."""


class EvidencePersistenceConflict(PersistenceConflict):
    """An ExecutionEvidence row exists with a conflicting envelope."""


class EnergySettlementConflict(PersistenceConflict):
    """A durable energy row exists with conflicting usage for the same settlement id."""


class ReconciliationConflict(IntegrationError):
    """Journal/DB/target reconciliation found an inconsistent durable state."""


class RecoveryInvariantViolation(IntegrationError):
    """Recovery observed an impossible durable state (e.g. journal COMPLETED, DB missing)."""
