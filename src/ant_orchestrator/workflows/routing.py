"""Pure retry/regroup routing + RetryGrant (PHASE_4_PLAN C.9b/D.4).

Deterministic functions over counters; no I/O, no clock, no persistence. The retry
budget is ``effective_retry_limit = base_retry_limit + retry_extension_count`` and is
always computed, never stored. ``base_retry_limit = WORKFLOW_MAX_RETRIES`` (=2) yields
three attempts (initial + 2 retries) before a RETRY_LIMIT gate is required.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ant_orchestrator.config.constants import (
    WORKFLOW_MAX_REGROUPS,
    WORKFLOW_MAX_RETRY_EXTENSIONS,
)
from ant_orchestrator.core.domain.enums import GateType


class RetryDecision(Enum):
    """Outcome of a retry routing check."""

    RETRY = "retry"
    ESCALATE = "escalate"


class RegroupDecision(Enum):
    """Outcome of a regroup routing check."""

    REGROUP = "regroup"
    ESCALATE = "escalate"


class GrantDecision(Enum):
    """Outcome of a retry-extension grant request."""

    GRANTED = "granted"
    DENIED = "denied"


class RouteReason(Enum):
    """Stable reason codes for routing decisions."""

    WITHIN_RETRY_BUDGET = "within_retry_budget"
    RETRY_BUDGET_EXHAUSTED = "retry_budget_exhausted"
    WITHIN_REGROUP_BUDGET = "within_regroup_budget"
    REGROUP_BUDGET_EXHAUSTED = "regroup_budget_exhausted"
    EXTENSION_GRANTED = "extension_granted"
    EXTENSION_BOUND_REACHED = "extension_bound_reached"


@dataclass(frozen=True, slots=True)
class RetryRoute:
    """Result of ``route_retry`` (carries the next ``retry_count``)."""

    decision: RetryDecision
    reason: RouteReason
    retry_count: int
    gate_type: GateType | None = None


@dataclass(frozen=True, slots=True)
class RegroupRoute:
    """Result of ``route_regroup`` (carries the next ``regroup_count``)."""

    decision: RegroupDecision
    reason: RouteReason
    regroup_count: int
    gate_type: GateType | None = None


@dataclass(frozen=True, slots=True)
class GrantResult:
    """Result of ``grant_retry_extension`` (carries the next ``retry_extension_count``)."""

    decision: GrantDecision
    reason: RouteReason
    retry_extension_count: int


def effective_retry_limit(base_retry_limit: int, retry_extension_count: int) -> int:
    """Compute the effective retry budget (never persisted as a field)."""
    return base_retry_limit + retry_extension_count


def route_retry(
    *,
    retry_count: int,
    base_retry_limit: int,
    retry_extension_count: int,
) -> RetryRoute:
    """RETRY (incrementing retry_count by one) while under budget, else ESCALATE."""
    limit = effective_retry_limit(base_retry_limit, retry_extension_count)
    if retry_count < limit:
        return RetryRoute(
            decision=RetryDecision.RETRY,
            reason=RouteReason.WITHIN_RETRY_BUDGET,
            retry_count=retry_count + 1,
        )
    return RetryRoute(
        decision=RetryDecision.ESCALATE,
        reason=RouteReason.RETRY_BUDGET_EXHAUSTED,
        retry_count=retry_count,
        gate_type=GateType.RETRY_LIMIT,
    )


def route_regroup(
    *,
    regroup_count: int,
    max_regroups: int = WORKFLOW_MAX_REGROUPS,
) -> RegroupRoute:
    """REGROUP (incrementing regroup_count by one) while under budget, else ESCALATE."""
    if regroup_count < max_regroups:
        return RegroupRoute(
            decision=RegroupDecision.REGROUP,
            reason=RouteReason.WITHIN_REGROUP_BUDGET,
            regroup_count=regroup_count + 1,
        )
    return RegroupRoute(
        decision=RegroupDecision.ESCALATE,
        reason=RouteReason.REGROUP_BUDGET_EXHAUSTED,
        regroup_count=regroup_count,
        gate_type=GateType.SCOPE_CHANGE,
    )


def grant_retry_extension(
    *,
    retry_extension_count: int,
    max_extensions: int = WORKFLOW_MAX_RETRY_EXTENSIONS,
) -> GrantResult:
    """Grant one extension (extension_count += 1) while under the hard bound, else DENY.

    A denied grant is fail-closed — it prevents an unbounded approval loop and never
    mutates a stored ``effective_retry_limit`` (which is always computed).
    """
    if retry_extension_count < max_extensions:
        return GrantResult(
            decision=GrantDecision.GRANTED,
            reason=RouteReason.EXTENSION_GRANTED,
            retry_extension_count=retry_extension_count + 1,
        )
    return GrantResult(
        decision=GrantDecision.DENIED,
        reason=RouteReason.EXTENSION_BOUND_REACHED,
        retry_extension_count=retry_extension_count,
    )
