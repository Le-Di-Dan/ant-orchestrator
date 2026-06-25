"""Energy port — typed contracts for measurement, budget, reservation and enforcement (CP7/CP8).

Defines resource kinds, budget DTO, reservation status, error taxonomy (CP7) plus
action plan, routing/enforcement/approval contracts, and manager Protocol (CP8).
Callers depend on this port without importing concrete ``energy/`` implementation.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Protocol, runtime_checkable

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from ant_orchestrator.errors import AntError

_RESOURCE_UNITS: Final = {
    "tokens": "integer token count",
    "api_calls": "integer call count",
    "wall_time_ms": "integer milliseconds",
    "retries": "integer retry count",
    "human_approvals": "integer approval count",
}


class ResourceKind(Enum):
    """A measurable resource governed by energy policy."""

    TOKENS = "tokens"
    API_CALLS = "api_calls"
    WALL_TIME = "wall_time_ms"
    RETRIES = "retries"
    HUMAN_APPROVALS = "human_approvals"


class MeasurementStatus(Enum):
    """Whether a measurement is estimated or actually observed."""

    ESTIMATED = "estimated"
    MEASURED = "measured"


class ReservationStatus(Enum):
    """Lifecycle state of an energy reservation."""

    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"
    EXPIRED = "expired"


class EnergyBudget:
    """Immutable resource limits. Missing resource kind = not governed."""

    __slots__ = ("_limits",)

    def __init__(self, limits: dict[ResourceKind, int]) -> None:
        for kind, value in limits.items():
            if value < 0:
                raise InvariantViolation(f"EnergyBudget limit for {kind.value} must be >= 0")
        self._limits: MappingProxyType[ResourceKind, int] = MappingProxyType(dict(limits))

    @property
    def limits(self) -> MappingProxyType[ResourceKind, int]:
        return self._limits

    def limit_for(self, kind: ResourceKind) -> int | None:
        return self._limits.get(kind)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, EnergyBudget):
            return NotImplemented
        return dict(self._limits) == dict(other._limits)

    def __repr__(self) -> str:
        return f"EnergyBudget(limits={dict(self._limits)})"


class EnergyError(AntError):
    """Base class for energy-related errors."""


class EnergyBudgetExceededError(EnergyError):
    """A reservation cannot be fulfilled within the remaining budget."""


class EnergyReservationError(EnergyError):
    """An invalid operation on a reservation (wrong state, not found, etc.)."""


# ---------------------------------------------------------------------------
# CP8 — enforcement, routing, approval, and action plan contracts
# ---------------------------------------------------------------------------


class ActionKind(Enum):
    """The type of action being energy-governed."""

    LOCAL_LLM_INFERENCE = "local_llm_inference"
    CLOUD_LLM_INFERENCE = "cloud_llm_inference"
    TOOL_EXECUTION = "tool_execution"
    DETERMINISTIC_COMPUTE = "deterministic_compute"
    CACHE_LOOKUP = "cache_lookup"


class CapabilityKind(Enum):
    """The capability required to execute an action."""

    LLM_INFERENCE = "llm_inference"
    CODE_EXECUTION = "code_execution"
    FILE_OPERATION = "file_operation"
    DETERMINISTIC = "deterministic"
    CACHE_ONLY = "cache_only"


class QualityRequirement(Enum):
    """Minimum quality level required for the action."""

    ANY = "any"
    LOCAL_CAPABLE = "local_capable"
    CLOUD_REQUIRED = "cloud_required"


class EnergyDecision(Enum):
    """Typed outcome from energy enforcement or routing."""

    ALLOW = "allow"
    USE_DETERMINISTIC_TOOL = "use_deterministic_tool"
    USE_CACHE = "use_cache"
    ROUTE_LOCAL = "route_local"
    ESCALATE_CLOUD = "escalate_cloud"
    DOWNGRADE = "downgrade"
    PENDING_APPROVAL = "pending_approval"
    REJECT = "reject"
    STOP = "stop"


class RoutingReason(Enum):
    """Typed reason for a routing decision."""

    DETERMINISTIC_AVAILABLE = "deterministic_available"
    CACHE_HIT = "cache_hit"
    LOCAL_CAPABLE = "local_capable"
    LOCAL_UNAVAILABLE = "local_unavailable"
    CAPABILITY_REQUIREMENT = "capability_requirement"
    QUALITY_REQUIREMENT = "quality_requirement"
    BUDGET_INSUFFICIENT = "budget_insufficient"
    MISSING_REQUIRED_BUDGET = "missing_required_budget"
    CLOUD_REQUIRES_APPROVAL = "cloud_requires_approval"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    SECURITY_POLICY_REJECTION = "security_policy_rejection"
    ROUTE_NOT_ELIGIBLE = "route_not_eligible"
    DOWNGRADE_AVAILABLE = "downgrade_available"
    WITHIN_BUDGET = "within_budget"
    RESERVATION_REJECTED = "reservation_rejected"
    RETRY_LIMIT_EXCEEDED = "retry_limit_exceeded"


class EnforcementReason(Enum):
    """Typed reason for an enforcement decision."""

    WITHIN_BUDGET = "within_budget"
    BUDGET_INSUFFICIENT = "budget_insufficient"
    MISSING_REQUIRED_BUDGET = "missing_required_budget"
    RESERVATION_REJECTED = "reservation_rejected"
    RUNTIME_BUDGET_EXCEEDED = "runtime_budget_exceeded"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    SECURITY_POLICY_REJECTION = "security_policy_rejection"
    RETRY_LIMIT_EXCEEDED = "retry_limit_exceeded"
    DOWNGRADE_AVAILABLE = "downgrade_available"
    DETERMINISTIC_NO_RESERVATION = "deterministic_no_reservation"
    CACHE_NO_RESERVATION = "cache_no_reservation"


class ApprovalReason(Enum):
    """Why an approval request was created."""

    CLOUD_REQUIRES_APPROVAL = "cloud_requires_approval"
    CONTEXT_BUDGET_EXCEEDED = "context_budget_exceeded"
    RUNTIME_BUDGET_EXCEEDED = "runtime_budget_exceeded"
    BUDGET_INSUFFICIENT = "budget_insufficient"
    RETRY_LIMIT_EXCEEDED = "retry_limit_exceeded"


class ApprovalConsequence(Enum):
    """What happens if approval is denied."""

    ACTION_REJECTED = "action_rejected"
    ACTION_DOWNGRADED = "action_downgraded"
    TASK_STOPPED = "task_stopped"


class BudgetCoverage(Enum):
    """Whether a required resource is covered by a governed budget limit."""

    GOVERNED = "governed"
    UNGOVERNED_ALLOWED = "ungoverned_allowed"
    MISSING_REQUIRED_LIMIT = "missing_required_limit"


@dataclass(frozen=True, slots=True)
class ContextDisposition:
    """Typed summary of context manifest outcome for energy enforcement."""

    dispatchable: bool
    required_budget_failure: bool
    required_security_failure: bool


@dataclass(frozen=True, slots=True)
class EnergyActionPlan:
    """Immutable action specification for energy-governed execution.

    No raw prompts, provider outputs, or secrets.
    """

    task_id: TaskId
    correlation_id: CorrelationId
    action_kind: ActionKind
    required_capability: CapabilityKind
    estimated_resources: MappingProxyType[ResourceKind, int]
    required_resources: frozenset[ResourceKind]
    deterministic_available: bool
    cache_valid: bool
    local_available: bool
    cloud_available: bool
    allow_auto_cloud: bool
    quality_requirement: QualityRequirement
    context_disposition: ContextDisposition | None = None
    retry_index: int = 0
    max_retries: int = 0
    downgrade_resources: MappingProxyType[ResourceKind, int] | None = None

    def __post_init__(self) -> None:
        for kind, amount in self.estimated_resources.items():
            if amount < 0:
                raise InvariantViolation(f"EnergyActionPlan: estimated {kind.value} must be >= 0")
        for kind, amount in (self.downgrade_resources or {}).items():
            if amount < 0:
                raise InvariantViolation(f"EnergyActionPlan: downgrade {kind.value} must be >= 0")
        if self.retry_index < 0:
            raise InvariantViolation("EnergyActionPlan.retry_index must be >= 0")
        if self.max_retries < 0:
            raise InvariantViolation("EnergyActionPlan.max_retries must be >= 0")

    def with_estimated_resources(
        self, resources: MappingProxyType[ResourceKind, int]
    ) -> EnergyActionPlan:
        """Return a copy with different estimated resources (for downgrade)."""
        return dataclasses.replace(self, estimated_resources=resources)


@dataclass(frozen=True, slots=True)
class EnergyActionResult:
    """Result of an EnergyBoundAction execution."""

    actual: MappingProxyType[ResourceKind, int]
    side_effect_started: bool = True


@runtime_checkable
class EnergyBoundAction(Protocol):
    """A typed action whose side effect is gated by EnergyManager."""

    def execute(self) -> EnergyActionResult:
        """Execute action; return actual resource amounts. Must not be called by routing."""
        ...


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    """Immutable approval handoff for Phase 4 resolution.

    No prompts, outputs, or secrets. Not persisted by CP8.
    """

    task_id: TaskId
    correlation_id: CorrelationId
    action_kind: ActionKind
    current_budget: EnergyBudget
    required_additional: MappingProxyType[ResourceKind, int]
    proposed_route: EnergyDecision
    reason: ApprovalReason
    alternatives_tried: tuple[EnergyDecision, ...]
    consequence_if_denied: ApprovalConsequence
    created_at: UtcTimestamp


@dataclass(frozen=True, slots=True)
class EnergyManagerResult:
    """Typed result from EnergyManager.execute()."""

    decision: EnergyDecision
    reason: RoutingReason | EnforcementReason
    approval_request: ApprovalRequest | None = None
    action_result: EnergyActionResult | None = None
    reservation_id: str | None = None
    audit_failure: bool = False
