"""Framework-neutral graph-state contract + JSON-safety validation (PHASE_4_PLAN C.3).

``GraphState`` is a plain ``TypedDict`` — it does NOT import LangGraph. The state must
stay JSON-safe at all times: only primitives, lists, and string-keyed dicts are
allowed (no enums, value objects, tuples, bytes, exceptions, callbacks, repositories,
adapters or secrets). Retry state is owned here; ``effective_retry_limit`` is always
*computed*, never stored.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from enum import Enum
from typing import TypedDict

from ant_orchestrator.config.constants import GRAPH_STATE_SCHEMA_VERSION
from ant_orchestrator.errors import AntError

__all__ = [
    "GRAPH_STATE_SCHEMA_VERSION",
    "GraphState",
    "GraphStateError",
    "SchemaCompatibility",
    "assert_json_safe",
    "canonical_dump",
    "check_schema_version",
    "effective_retry_limit",
    "new_graph_state",
    "round_trip",
    "sanitize_payload",
]


class GraphStateError(AntError):
    """A graph-state value violated the JSON-safe contract."""


class SchemaCompatibility(Enum):
    """Whether a state's schema version matches the running code."""

    COMPATIBLE = "compatible"
    UNKNOWN_VERSION = "unknown_version"


class GraphState(TypedDict, total=False):
    """Typed, minimal, JSON-safe workflow state (PHASE_4_PLAN C.3)."""

    graph_state_schema_version: int
    task_id: str
    workflow_run_id: str
    phase: str
    plan: dict[str, object]
    context_ref: str
    # Phase 5 CP2: prepared context bound off-graph (anti-TOCTOU). Both are JSON-safe
    # references — the package reference and the manifest digest a proposal binds to.
    context_package_ref: str
    manifest_digest: str
    # Phase 5 CP6: the durable proposal the approval binds to, and the resolved approval
    # reference. All optional/additive (schema 2 still round-trips); the production Phase 5
    # path requires them at runtime and fails closed when absent (they never fall back).
    proposal_ref: str
    proposal_digest: str
    approval_ref: str
    action_intent: dict[str, object]
    approval_intent: dict[str, object]
    approval_decision: dict[str, object] | None
    validation_result: dict[str, object]
    review_result: dict[str, object]
    base_retry_limit: int
    retry_count: int
    retry_extension_count: int
    regroup_count: int
    approval_gate_sequence: int
    execution_attempt_ref: str | None
    evidence_refs: list[str]
    final_outcome: str | None
    error_summary: str | None
    # CP4: Test Ant compact outcome (routing only; no raw output/exception/host path).
    # Absent before node `test` runs; reset on retry/regroup. JSON-safe string refs only.
    test_status: str | None  # "pass"|"retryable"|"escalate"|"fatal"|"cancelled"
    test_outcome: str | None  # WorkerOutcome value
    test_failure_category: str | None  # FailureCategory value
    test_reason_code: str | None  # TestReasonCode value
    test_recovery_disposition: str | None  # RecoveryDisposition value
    test_attempt_ref: str | None  # stable attempt identity
    test_logical_action_ref: str | None  # stable logical action identity
    test_evidence_refs: list[str]  # bounded sanitized references


_JSON_SCALARS = (str, int, float, bool)


def _assert_value(path: str, value: object) -> None:
    if value is None or isinstance(value, _JSON_SCALARS):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            _assert_value(f"{path}[{index}]", item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise GraphStateError(
                    f"{path}: dict key must be a string, got {type(key).__name__}"
                )
            _assert_value(f"{path}.{key}", item)
        return
    raise GraphStateError(f"{path}: non-JSON-safe value of type {type(value).__name__}")


def assert_json_safe(state: Mapping[str, object]) -> None:
    """Raise ``GraphStateError`` unless every value is a JSON-safe primitive/list/dict.

    Enums, value objects, tuples, bytes, exceptions, callbacks, repository/adapter
    instances are all rejected — they must be converted to primitives first.
    """
    for key, value in state.items():
        if not isinstance(key, str):
            raise GraphStateError(f"top-level key must be a string, got {type(key).__name__}")
        _assert_value(key, value)


def canonical_dump(state: Mapping[str, object]) -> str:
    """Return a canonical, stable JSON string (validated JSON-safe first)."""
    assert_json_safe(state)
    return json.dumps(dict(state), sort_keys=True, ensure_ascii=False)


def round_trip(state: Mapping[str, object]) -> dict[str, object]:
    """Dump to canonical JSON and parse back (proves semantic preservation)."""
    parsed = json.loads(canonical_dump(state))
    assert isinstance(parsed, dict)
    return {str(key): value for key, value in parsed.items()}


def sanitize_payload(payload: Mapping[str, object]) -> dict[str, object]:
    """Return a JSON-safe copy of ``payload`` or raise if any value is unsupported.

    Used by intent builders so a non-primitive (e.g. a secret-bearing object) can
    never be auto-injected into graph state.
    """
    assert_json_safe(payload)
    return {str(key): value for key, value in payload.items()}


def effective_retry_limit(state: Mapping[str, object]) -> int:
    """Compute ``base_retry_limit + retry_extension_count`` (never stored)."""
    base = state.get("base_retry_limit", 0)
    extension = state.get("retry_extension_count", 0)
    if not isinstance(base, int) or not isinstance(extension, int):
        raise GraphStateError("retry-limit fields must be integers")
    return base + extension


def check_schema_version(state: Mapping[str, object]) -> SchemaCompatibility:
    """Classify the state's schema version (no recovery orchestration in CP2)."""
    found = state.get("graph_state_schema_version")
    if found == GRAPH_STATE_SCHEMA_VERSION:
        return SchemaCompatibility.COMPATIBLE
    return SchemaCompatibility.UNKNOWN_VERSION


def new_graph_state(
    *,
    task_id: str,
    workflow_run_id: str,
    base_retry_limit: int,
) -> GraphState:
    """Build a fresh initial state with safe defaults (no shared mutable defaults)."""
    return GraphState(
        graph_state_schema_version=GRAPH_STATE_SCHEMA_VERSION,
        task_id=task_id,
        workflow_run_id=workflow_run_id,
        phase="plan",
        base_retry_limit=base_retry_limit,
        retry_count=0,
        retry_extension_count=0,
        regroup_count=0,
        approval_gate_sequence=0,
        evidence_refs=[],
        # CP4: compact test fields (additive optional, default None/[]).
        test_status=None,
        test_outcome=None,
        test_failure_category=None,
        test_reason_code=None,
        test_recovery_disposition=None,
        test_attempt_ref=None,
        test_logical_action_ref=None,
        test_evidence_refs=[],
    )
