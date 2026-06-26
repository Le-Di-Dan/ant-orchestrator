"""GraphState contract + JSON-safety tests (CP2)."""

from __future__ import annotations

import pytest

from ant_orchestrator.config.constants import GRAPH_STATE_SCHEMA_VERSION
from ant_orchestrator.core.domain.enums import GateType
from ant_orchestrator.workflows.state import (
    GraphStateError,
    SchemaCompatibility,
    assert_json_safe,
    canonical_dump,
    check_schema_version,
    effective_retry_limit,
    new_graph_state,
    round_trip,
)


def _state() -> dict[str, object]:
    return dict(new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=2))


def test_new_state_has_safe_defaults() -> None:
    state = _state()
    assert state["graph_state_schema_version"] == GRAPH_STATE_SCHEMA_VERSION
    assert state["retry_count"] == 0
    assert state["retry_extension_count"] == 0
    assert state["regroup_count"] == 0
    assert state["approval_gate_sequence"] == 0
    assert state["evidence_refs"] == []


def test_evidence_refs_default_is_not_shared() -> None:
    first = new_graph_state(task_id="T1", workflow_run_id="R1", base_retry_limit=2)
    second = new_graph_state(task_id="T2", workflow_run_id="R2", base_retry_limit=2)
    first["evidence_refs"].append("e1")
    assert second["evidence_refs"] == []  # no shared mutable default


def test_json_safe_round_trip_preserves_state() -> None:
    state = _state()
    state["plan"] = {"goal": "g", "plan_revision": 0}
    state["evidence_refs"] = ["e1", "e2"]
    assert round_trip(state) == state
    assert canonical_dump(state)  # canonical dump succeeds


def test_effective_retry_limit_is_computed_not_stored() -> None:
    state = _state()
    state["retry_extension_count"] = 1
    assert "effective_retry_limit" not in state
    assert effective_retry_limit(state) == 3  # base 2 + extension 1


def test_schema_version_classification() -> None:
    state = _state()
    assert check_schema_version(state) is SchemaCompatibility.COMPATIBLE
    state["graph_state_schema_version"] = 999
    assert check_schema_version(state) is SchemaCompatibility.UNKNOWN_VERSION


def test_reject_enum_value() -> None:
    with pytest.raises(GraphStateError):
        assert_json_safe({"gate": GateType.RETRY_LIMIT})


def test_reject_exception_object() -> None:
    with pytest.raises(GraphStateError):
        assert_json_safe({"err": ValueError("boom")})


def test_reject_bytes_and_callable_and_tuple() -> None:
    with pytest.raises(GraphStateError):
        assert_json_safe({"b": b"raw"})
    with pytest.raises(GraphStateError):
        assert_json_safe({"cb": lambda: None})
    with pytest.raises(GraphStateError):
        assert_json_safe({"t": (1, 2)})


def test_reject_nested_unsupported_object() -> None:
    with pytest.raises(GraphStateError):
        assert_json_safe({"plan": {"obj": object()}})


def test_reject_non_string_dict_key() -> None:
    with pytest.raises(GraphStateError):
        assert_json_safe({"plan": {1: "x"}})
