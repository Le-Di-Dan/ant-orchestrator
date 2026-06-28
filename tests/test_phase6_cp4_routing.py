"""CP4 — pure routing tests for route_after_test_validation (§11.1, §6, §F)."""

from __future__ import annotations

import pytest

from ant_orchestrator.workflows.graph_support import (
    PHASE_CANCELLED,
    PHASE_FAILED,
    PHASE_PREPARE_INTENT,
    PHASE_REVIEW,
    PHASE_TEST,
)
from ant_orchestrator.workflows.state import GraphState, new_graph_state
from ant_orchestrator.workflows.test_routing import route_after_test_validation


def _state(**overrides: object) -> GraphState:
    base = new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=2)
    base.update(overrides)  # type: ignore[arg-type]
    return base


# ---------------------------------------------------------------------------
# Pass
# ---------------------------------------------------------------------------


def test_pass_routes_to_review() -> None:
    route = route_after_test_validation(_state(), "pass")
    assert route["phase"] == PHASE_REVIEW
    assert "retry_count" not in route
    assert "gate_type" not in route


# ---------------------------------------------------------------------------
# Retryable (transient + budget)
# ---------------------------------------------------------------------------


def test_retryable_within_budget_routes_to_test_and_increments_counter() -> None:
    route = route_after_test_validation(_state(retry_count=0), "retryable")
    assert route["phase"] == PHASE_TEST
    assert route["retry_count"] == 1


def test_retryable_second_retry_still_within_budget() -> None:
    route = route_after_test_validation(_state(retry_count=1), "retryable")
    assert route["phase"] == PHASE_TEST
    assert route["retry_count"] == 2


def test_retryable_budget_exhausted_escalates_to_retry_limit() -> None:
    # base_retry_limit=2, retry_count=2 → exhausted
    route = route_after_test_validation(_state(retry_count=2), "retryable")
    assert route["phase"] == PHASE_PREPARE_INTENT
    from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType

    assert route["gate_type"] is GateType.RETRY_LIMIT
    assert route["continuation"] is ApprovalContinuation.EXECUTE
    assert "retry_count" not in route  # counter NOT incremented


def test_retryable_with_extension_still_retries() -> None:
    # base=2, extension=1 → limit=3; retry_count=2 < 3 → retry allowed
    route = route_after_test_validation(_state(retry_count=2, retry_extension_count=1), "retryable")
    assert route["phase"] == PHASE_TEST
    assert route["retry_count"] == 3


# ---------------------------------------------------------------------------
# Escalate (covers timeout, deterministic, isolation, unknown)
# ---------------------------------------------------------------------------


def test_escalate_routes_to_scope_change_gate() -> None:
    from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType

    route = route_after_test_validation(_state(), "escalate")
    assert route["phase"] == PHASE_PREPARE_INTENT
    assert route["gate_type"] is GateType.SCOPE_CHANGE
    assert route["continuation"] is ApprovalContinuation.REPLAN


def test_escalate_does_not_increment_retry_count() -> None:
    route = route_after_test_validation(_state(retry_count=1), "escalate")
    assert "retry_count" not in route


# ---------------------------------------------------------------------------
# Fatal (permanent failure)
# ---------------------------------------------------------------------------


def test_fatal_routes_to_failed() -> None:
    route = route_after_test_validation(_state(), "fatal")
    assert route["phase"] == PHASE_FAILED


def test_fatal_no_gate() -> None:
    route = route_after_test_validation(_state(), "fatal")
    assert "gate_type" not in route


# ---------------------------------------------------------------------------
# Cancelled
# ---------------------------------------------------------------------------


def test_cancelled_routes_to_cancelled() -> None:
    route = route_after_test_validation(_state(), "cancelled")
    assert route["phase"] == PHASE_CANCELLED


# ---------------------------------------------------------------------------
# Unknown status → safe escalation
# ---------------------------------------------------------------------------


def test_unknown_status_escalates_safely() -> None:
    from ant_orchestrator.core.domain.enums import GateType

    route = route_after_test_validation(_state(), "UNRECOGNIZED_STATUS_XYZ")
    assert route["phase"] == PHASE_PREPARE_INTENT
    assert route["gate_type"] is GateType.SCOPE_CHANGE


def test_empty_status_escalates_safely() -> None:
    from ant_orchestrator.core.domain.enums import GateType

    route = route_after_test_validation(_state(), "")
    assert route["phase"] == PHASE_PREPARE_INTENT
    assert route["gate_type"] is GateType.SCOPE_CHANGE


# ---------------------------------------------------------------------------
# Exhaustive: every disposition category has a defined route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected_phase",
    [
        ("pass", PHASE_REVIEW),
        ("fatal", PHASE_FAILED),
        ("cancelled", PHASE_CANCELLED),
        ("escalate", PHASE_PREPARE_INTENT),
    ],
)
def test_status_routing_table(status: str, expected_phase: str) -> None:
    route = route_after_test_validation(_state(), status)
    assert route["phase"] == expected_phase


# ---------------------------------------------------------------------------
# Retry routing does NOT touch regroup_count
# ---------------------------------------------------------------------------


def test_retry_does_not_change_regroup_count() -> None:
    route = route_after_test_validation(_state(regroup_count=0, retry_count=0), "retryable")
    assert "regroup_count" not in route


# ---------------------------------------------------------------------------
# Escalate routing does NOT touch retry_count (plain deadline, deterministic)
# ---------------------------------------------------------------------------


def test_escalate_does_not_touch_retry_count() -> None:
    route = route_after_test_validation(_state(retry_count=1), "escalate")
    assert "retry_count" not in route
