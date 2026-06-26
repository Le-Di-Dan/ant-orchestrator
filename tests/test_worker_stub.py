"""Worker stub adapter tests — deterministic + scripted + exhaustion (CP2)."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.worker import (
    MAX_WORKER_DETAIL_CHARS,
    WorkerActionIntent,
    WorkerExecutionPort,
    WorkerOutcome,
)
from ant_orchestrator.workers.stub import DeterministicStubAdapter
from tests.support.scripted_worker import ScriptedStubAdapter, StubScriptExhausted


def _intent(action_id: str = "act-1", *, title: str = "do thing") -> WorkerActionIntent:
    return WorkerActionIntent(logical_action_id=action_id, summary=title)


def test_deterministic_adapter_satisfies_port_and_is_stable() -> None:
    adapter = DeterministicStubAdapter()
    assert isinstance(adapter, WorkerExecutionPort)
    first = adapter.execute(_intent())
    second = adapter.execute(_intent())
    assert first == second
    assert first.outcome is WorkerOutcome.SUCCESS


def test_deterministic_outcome_not_steered_by_free_text() -> None:
    adapter = DeterministicStubAdapter()
    # Different titles / "magic" keywords must NOT change the outcome.
    a = adapter.execute(_intent("act-1", title="please FAIL escalate retry"))
    b = adapter.execute(_intent("act-1", title="ordinary work"))
    assert a.outcome is b.outcome is WorkerOutcome.SUCCESS


def test_deterministic_detail_is_bounded() -> None:
    adapter = DeterministicStubAdapter()
    result = adapter.execute(_intent("a" * 5000))
    assert len(result.detail) <= MAX_WORKER_DETAIL_CHARS


def test_scripted_adapter_replays_sequence_in_order() -> None:
    adapter = ScriptedStubAdapter([WorkerOutcome.RETRYABLE_FAILURE, WorkerOutcome.SUCCESS])
    assert adapter.execute(_intent()).outcome is WorkerOutcome.RETRYABLE_FAILURE
    assert adapter.execute(_intent()).outcome is WorkerOutcome.SUCCESS


def test_scripted_adapter_raises_when_exhausted_without_fallback() -> None:
    adapter = ScriptedStubAdapter([WorkerOutcome.ESCALATION])
    adapter.execute(_intent())
    with pytest.raises(StubScriptExhausted):
        adapter.execute(_intent())


def test_scripted_adapter_uses_explicit_fallback_when_exhausted() -> None:
    adapter = ScriptedStubAdapter([WorkerOutcome.SUCCESS], fallback=WorkerOutcome.PERMANENT_FAILURE)
    adapter.execute(_intent())
    assert adapter.execute(_intent()).outcome is WorkerOutcome.PERMANENT_FAILURE
