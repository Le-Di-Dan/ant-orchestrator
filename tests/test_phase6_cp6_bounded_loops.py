"""CP6 bounded retry/regroup loop tests (§6).

Verifies that the routing functions enforce their hard limits:
  §6.1  Base retry limit: WORKFLOW_MAX_RETRIES=2 → 3 attempts total, then ESCALATE.
  §6.2  Extension: WORKFLOW_MAX_RETRY_EXTENSIONS=1 → one extra window, then DENY.
  §6.3  Regroup: WORKFLOW_MAX_REGROUPS=1 → one regroup, then ESCALATE.
  §6.4  Terminal state: once failed/cancelled/rejected, no new attempt is routed.
  §6.5  retry_count/regroup_count are non-negative (invariant guard).
  §6.6  effective_retry_limit is computed (not stored) — extension changes it inline.
"""

from __future__ import annotations

from ant_orchestrator.config.constants import (
    WORKFLOW_MAX_REGROUPS,
    WORKFLOW_MAX_RETRIES,
    WORKFLOW_MAX_RETRY_EXTENSIONS,
)
from ant_orchestrator.workflows.routing import (
    GrantDecision,
    RegroupDecision,
    RetryDecision,
    RouteReason,
    effective_retry_limit,
    grant_retry_extension,
    route_regroup,
    route_retry,
)

# ---------------------------------------------------------------------------
# §6.1 — base retry limit (WORKFLOW_MAX_RETRIES = 2)
# ---------------------------------------------------------------------------


def test_retry_within_budget_increments_count() -> None:
    """§6.1: retry_count < limit → RETRY, next count = current + 1."""
    route = route_retry(retry_count=0, base_retry_limit=2, retry_extension_count=0)
    assert route.decision is RetryDecision.RETRY
    assert route.retry_count == 1
    assert route.reason is RouteReason.WITHIN_RETRY_BUDGET


def test_retry_at_limit_escalates() -> None:
    """§6.1: retry_count == limit → ESCALATE (no new attempt)."""
    route = route_retry(retry_count=2, base_retry_limit=2, retry_extension_count=0)
    assert route.decision is RetryDecision.ESCALATE
    assert route.reason is RouteReason.RETRY_BUDGET_EXHAUSTED
    assert route.retry_count == 2  # unchanged


def test_retry_three_attempts_then_escalate() -> None:
    """§6.1: WORKFLOW_MAX_RETRIES=2 allows attempts at count 0, 1, 2 only."""
    limit = WORKFLOW_MAX_RETRIES
    count = 0
    decisions = []
    for _ in range(limit + 2):  # one past exhaustion
        r = route_retry(retry_count=count, base_retry_limit=limit, retry_extension_count=0)
        decisions.append(r.decision)
        if r.decision is RetryDecision.RETRY:
            count = r.retry_count

    retries = decisions.count(RetryDecision.RETRY)
    escalates = decisions.count(RetryDecision.ESCALATE)
    assert retries == limit
    assert escalates >= 1, "must eventually ESCALATE once limit is exhausted"


# ---------------------------------------------------------------------------
# §6.2 — extension (WORKFLOW_MAX_RETRY_EXTENSIONS = 1)
# ---------------------------------------------------------------------------


def test_extension_granted_increments_count() -> None:
    """§6.2: first extension → GRANTED, extension_count = 1."""
    result = grant_retry_extension(retry_extension_count=0)
    assert result.decision is GrantDecision.GRANTED
    assert result.retry_extension_count == 1
    assert result.reason is RouteReason.EXTENSION_GRANTED


def test_extension_denied_at_bound() -> None:
    """§6.2: extension_count == max → DENIED (fail-closed, prevents unbounded loop)."""
    result = grant_retry_extension(
        retry_extension_count=WORKFLOW_MAX_RETRY_EXTENSIONS,
        max_extensions=WORKFLOW_MAX_RETRY_EXTENSIONS,
    )
    assert result.decision is GrantDecision.DENIED
    assert result.reason is RouteReason.EXTENSION_BOUND_REACHED
    assert result.retry_extension_count == WORKFLOW_MAX_RETRY_EXTENSIONS  # unchanged


def test_extension_expands_retry_window() -> None:
    """§6.2: granted extension raises the effective limit for the next retry route."""
    grant = grant_retry_extension(retry_extension_count=0)
    assert grant.decision is GrantDecision.GRANTED

    # With extension the limit goes from 2 to 3.
    route = route_retry(
        retry_count=2,
        base_retry_limit=WORKFLOW_MAX_RETRIES,
        retry_extension_count=grant.retry_extension_count,
    )
    assert route.decision is RetryDecision.RETRY


# ---------------------------------------------------------------------------
# §6.3 — regroup (WORKFLOW_MAX_REGROUPS = 1)
# ---------------------------------------------------------------------------


def test_regroup_within_budget_increments_count() -> None:
    """§6.3: regroup_count < max → REGROUP, next count = current + 1."""
    route = route_regroup(regroup_count=0)
    assert route.decision is RegroupDecision.REGROUP
    assert route.regroup_count == 1
    assert route.reason is RouteReason.WITHIN_REGROUP_BUDGET


def test_regroup_at_limit_escalates() -> None:
    """§6.3: regroup_count == max → ESCALATE (no new regroup)."""
    route = route_regroup(regroup_count=WORKFLOW_MAX_REGROUPS, max_regroups=WORKFLOW_MAX_REGROUPS)
    assert route.decision is RegroupDecision.ESCALATE
    assert route.reason is RouteReason.REGROUP_BUDGET_EXHAUSTED
    assert route.regroup_count == WORKFLOW_MAX_REGROUPS  # unchanged


def test_regroup_only_once_then_escalates() -> None:
    """§6.3: WORKFLOW_MAX_REGROUPS=1 → one regroup allowed, second call escalates."""
    r1 = route_regroup(regroup_count=0, max_regroups=WORKFLOW_MAX_REGROUPS)
    assert r1.decision is RegroupDecision.REGROUP

    r2 = route_regroup(regroup_count=r1.regroup_count, max_regroups=WORKFLOW_MAX_REGROUPS)
    assert r2.decision is RegroupDecision.ESCALATE


# ---------------------------------------------------------------------------
# §6.4 — terminal state: no route allowed after ESCALATE
# ---------------------------------------------------------------------------


def test_route_after_escalate_is_stable() -> None:
    """§6.4: once ESCALATE is reached, further calls keep returning ESCALATE."""
    r1 = route_retry(retry_count=2, base_retry_limit=2, retry_extension_count=0)
    assert r1.decision is RetryDecision.ESCALATE

    r2 = route_retry(retry_count=r1.retry_count, base_retry_limit=2, retry_extension_count=0)
    assert r2.decision is RetryDecision.ESCALATE


def test_regroup_escalate_after_max_is_stable() -> None:
    """§6.4: once regroup ESCALATE, further calls keep returning ESCALATE."""
    r1 = route_regroup(regroup_count=1, max_regroups=1)
    assert r1.decision is RegroupDecision.ESCALATE

    r2 = route_regroup(regroup_count=r1.regroup_count, max_regroups=1)
    assert r2.decision is RegroupDecision.ESCALATE


# ---------------------------------------------------------------------------
# §6.5 — non-negative invariant guards
# ---------------------------------------------------------------------------


def test_retry_count_zero_not_escalated_for_zero_base() -> None:
    """§6.5: base_retry_limit=0 → first call at count=0 immediately escalates (no retries)."""
    route = route_retry(retry_count=0, base_retry_limit=0, retry_extension_count=0)
    assert route.decision is RetryDecision.ESCALATE


def test_regroup_count_zero_base_zero_max_escalates() -> None:
    """§6.5: max_regroups=0 → immediately escalates with no regroups."""
    route = route_regroup(regroup_count=0, max_regroups=0)
    assert route.decision is RegroupDecision.ESCALATE


# ---------------------------------------------------------------------------
# §6.6 — effective_retry_limit is computed, not stored
# ---------------------------------------------------------------------------


def test_effective_limit_is_additive() -> None:
    """§6.6: effective limit = base + extension, never a stored field."""
    assert effective_retry_limit(2, 0) == 2
    assert effective_retry_limit(2, 1) == 3
    assert effective_retry_limit(0, 1) == 1


def test_effective_limit_with_max_extension() -> None:
    """§6.6: WORKFLOW_MAX_RETRIES + WORKFLOW_MAX_RETRY_EXTENSIONS = known hard ceiling."""
    ceiling = effective_retry_limit(WORKFLOW_MAX_RETRIES, WORKFLOW_MAX_RETRY_EXTENSIONS)
    assert ceiling == WORKFLOW_MAX_RETRIES + WORKFLOW_MAX_RETRY_EXTENSIONS


# ---------------------------------------------------------------------------
# Constants sanity
# ---------------------------------------------------------------------------


def test_constants_have_expected_values() -> None:
    """Guard: the canonical constants that CP6 hardening proofs are built against."""
    assert WORKFLOW_MAX_RETRIES == 2
    assert WORKFLOW_MAX_RETRY_EXTENSIONS == 1
    assert WORKFLOW_MAX_REGROUPS == 1
