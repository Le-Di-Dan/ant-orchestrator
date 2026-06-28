"""Pure Test Ant routing: route_after_test_validation (PHASE_6_PLAN CP4, §6).

Deterministic, no I/O, no LangGraph, no worker calls. The routing table implements the
canonical §F decision: only ``TRANSIENT`` with budget allows a Test Ant retry
(``PHASE_TEST``). Plain timeout, deterministic failure, isolation failure, and unknown all
route to a SCOPE_CHANGE gate — never back to the same Test Ant with the same strategy.
"""

from __future__ import annotations

from collections.abc import Mapping

from ant_orchestrator.core.domain.enums import ApprovalContinuation, GateType
from ant_orchestrator.workflows.graph_support import (
    PHASE_CANCELLED,
    PHASE_FAILED,
    PHASE_PREPARE_INTENT,
    PHASE_REVIEW,
    PHASE_TEST,
    as_int,
)
from ant_orchestrator.workflows.routing import RetryDecision, route_retry

__all__ = ["route_after_test_validation"]


def route_after_test_validation(state: Mapping[str, object], status: str) -> dict[str, object]:
    """Map a test validation status to the next graph phase.

    Status values (set by node ``test`` after TestExecutionPort.execute):

    * ``"pass"``       — TestAnt reported success → :data:`PHASE_REVIEW`.
    * ``"retryable"``  — TRANSIENT outcome, retry budget remaining → :data:`PHASE_TEST`
                         (Test Ant retry, NOT DocAnt). Budget exhausted → RETRY_LIMIT gate.
    * ``"escalate"``   — includes TEST_DEADLINE_EXCEEDED, deterministic test failure,
                         isolation unavailable/setup failure, UNKNOWN → SCOPE_CHANGE gate.
    * ``"fatal"``      — permanent/policy/boundary failure → :data:`PHASE_FAILED`.
    * ``"cancelled"``  — out-of-band cancellation → :data:`PHASE_CANCELLED`.

    Unknown statuses are treated as escalation (fail-safe).
    """
    if status == "pass":
        return {"phase": PHASE_REVIEW}
    if status == "retryable":
        route = route_retry(
            retry_count=as_int(state.get("retry_count")),
            base_retry_limit=as_int(state.get("base_retry_limit")),
            retry_extension_count=as_int(state.get("retry_extension_count")),
        )
        if route.decision is RetryDecision.RETRY:
            return {"phase": PHASE_TEST, "retry_count": route.retry_count}
        # Budget exhausted: RETRY_LIMIT gate (human/Queen may extend once).
        return {
            "phase": PHASE_PREPARE_INTENT,
            "gate_type": GateType.RETRY_LIMIT,
            "continuation": ApprovalContinuation.EXECUTE,
        }
    if status == "fatal":
        return {"phase": PHASE_FAILED}
    if status == "cancelled":
        return {"phase": PHASE_CANCELLED}
    # "escalate" and any unknown status → SCOPE_CHANGE (Queen decides REPLAN).
    # Covers: TEST_DEADLINE_EXCEEDED, DETERMINISTIC_TEST_FAILURE,
    # EXECUTION_ISOLATION_UNAVAILABLE, ISOLATION_SETUP_FAILURE, UNKNOWN, etc.
    return {
        "phase": PHASE_PREPARE_INTENT,
        "gate_type": GateType.SCOPE_CHANGE,
        "continuation": ApprovalContinuation.REPLAN,
    }
