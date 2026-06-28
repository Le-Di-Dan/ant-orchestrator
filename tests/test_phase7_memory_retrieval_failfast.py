"""Phase 7 CP5 — ContextSourcePreparerImpl fail-fast and backward-compat guard.

Covers:
  - criteria set + no retriever → InvariantViolation (fail-fast invariant)
  - no criteria + no retriever → None (backward-compat silent skip)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextConsumer,
)
from ant_orchestrator.application.ports.context_preparation import ContextPreparationInput
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.test_context_package import FakeFs

_TS = UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC))
_SOURCE = "docs/source/brief.md"
_BUDGET = ContextBudget(max_input_tokens=50_000, max_files=10, max_file_tokens=25_000)
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")


def _make_preparer(tmp_path: Path, *, retriever: object = None) -> ContextSourcePreparerImpl:
    from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
    from ant_orchestrator.context.selection import ContextSelector

    clock = FakeClock(_TS)
    ids = SequentialIdGenerator()
    builder = ContextPackageBuilder(
        fs=FakeFs({_SOURCE: "brief body"}),
        estimator=CharacterHeuristicEstimator(),
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=clock,
        id_gen=ids,
    )
    store = ContextPackageStore(tmp_path / "artifacts")
    return ContextSourcePreparerImpl(builder, store, memory_retriever=retriever)  # type: ignore[arg-type]


def _request(*, criteria: MemorySearchCriteria | None) -> ContextPreparationInput:
    return ContextPreparationInput(
        run_id="R-1",
        logical_action_id="act-1",
        consumer=_CONSUMER,
        approved_inputs=(_SOURCE,),
        budget=_BUDGET,
        memory_criteria=criteria,
    )


def test_criteria_set_no_retriever_raises_invariant(tmp_path: Path) -> None:
    preparer = _make_preparer(tmp_path, retriever=None)
    criteria = MemorySearchCriteria(task_id=TaskId("T-1"))
    req = _request(criteria=criteria)
    with pytest.raises(InvariantViolation, match="memory_retriever"):
        asyncio.run(preparer.prepare(req))


def test_no_criteria_no_retriever_returns_ref(tmp_path: Path) -> None:
    preparer = _make_preparer(tmp_path, retriever=None)
    req = _request(criteria=None)
    result = asyncio.run(preparer.prepare(req))
    assert result.context_package_ref != ""
    assert result.manifest_digest != ""
