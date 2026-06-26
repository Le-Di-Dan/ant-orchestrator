"""Retry/regroup router + RetryGrant tests (CP2)."""

from __future__ import annotations

from ant_orchestrator.core.domain.enums import GateType
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


def test_effective_retry_limit_is_base_plus_extension() -> None:
    assert effective_retry_limit(2, 0) == 2
    assert effective_retry_limit(2, 1) == 3


def test_base_two_allows_three_attempts_before_approval() -> None:
    # base=2 -> initial + 2 retries = 3 attempts; only then RETRY_LIMIT approval.
    retry_count = 0
    decisions = []
    for _ in range(4):
        route = route_retry(retry_count=retry_count, base_retry_limit=2, retry_extension_count=0)
        decisions.append(route.decision)
        if route.decision is RetryDecision.RETRY:
            assert route.retry_count == retry_count + 1  # increments by exactly one
            retry_count = route.retry_count
        else:
            assert route.gate_type is GateType.RETRY_LIMIT
            break
    assert decisions == [RetryDecision.RETRY, RetryDecision.RETRY, RetryDecision.ESCALATE]


def test_retry_extension_raises_effective_limit() -> None:
    # With one granted extension, retry_count=2 is still within budget (limit 3).
    route = route_retry(retry_count=2, base_retry_limit=2, retry_extension_count=1)
    assert route.decision is RetryDecision.RETRY
    assert route.retry_count == 3


def test_retry_grant_only_increments_extension_and_is_bounded() -> None:
    granted = grant_retry_extension(retry_extension_count=0)
    assert granted.decision is GrantDecision.GRANTED
    assert granted.reason is RouteReason.EXTENSION_GRANTED
    assert granted.retry_extension_count == 1
    # Hard bound (MAX_RETRY_EXTENSIONS=1): a second grant is fail-closed.
    denied = grant_retry_extension(retry_extension_count=1)
    assert denied.decision is GrantDecision.DENIED
    assert denied.reason is RouteReason.EXTENSION_BOUND_REACHED
    assert denied.retry_extension_count == 1


def test_regroup_allows_one_then_escalates_scope_change() -> None:
    first = route_regroup(regroup_count=0)
    assert first.decision is RegroupDecision.REGROUP
    assert first.regroup_count == 1
    second = route_regroup(regroup_count=1)
    assert second.decision is RegroupDecision.ESCALATE
    assert second.gate_type is GateType.SCOPE_CHANGE
    assert second.regroup_count == 1  # unchanged when escalating
