"""PHASE_5_PLAN CP6: production composition wiring + graph production-path branch."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.document_worker import DocumentationTask
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    CompositionConstraints,
    CompositionResult,
)
from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionOutcome,
)
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.energy.durable_lifecycle import DurableEnergyLifecycle
from ant_orchestrator.energy.worker_lifecycle import InMemoryEnergyLifecycle
from ant_orchestrator.integration.composition import build_documentation_execution
from ant_orchestrator.integration.errors import ProductionWorkerConfigMissing
from ant_orchestrator.workflows.graph_support import (
    execute_documentation_node as _execute_documentation,
)
from ant_orchestrator.workflows.nodes import PHASE_FAILED, PHASE_VALIDATE
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.test_phase5_cp5_documentation import _policy


class _FakeComposer:
    async def compose(
        self, task: DocumentationTask, context: ComposerContext, constraints: CompositionConstraints
    ) -> CompositionResult:  # pragma: no cover - not invoked in these tests
        raise NotImplementedError


class _FakePort:
    def __init__(self, outcome: DocumentationExecutionOutcome) -> None:
        self._outcome = outcome
        self.calls = 0

    def execute(self, **kwargs: object) -> DocumentationExecutionOutcome:
        self.calls += 1
        self.received = kwargs
        return self._outcome


def _build(tmp_path: Path, *, composer: object | None):  # type: ignore[no-untyped-def]
    return build_documentation_execution(
        composer=composer,  # type: ignore[arg-type]
        policy=_policy(tmp_path),
        uow_factory=lambda: None,  # type: ignore[arg-type, return-value]
        clock=FakeClock(UtcTimestamp(datetime(2026, 6, 27, tzinfo=UTC))),
        ids=SequentialIdGenerator(),
        workspace_root=tmp_path,
        artifacts_root=tmp_path / ".ant" / "artifacts",
    )


def test_missing_composer_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ProductionWorkerConfigMissing):
        _build(tmp_path, composer=None)


def test_production_uses_durable_not_in_memory_energy(tmp_path: Path) -> None:
    adapter = _build(tmp_path, composer=_FakeComposer())
    assert isinstance(adapter._energy, DurableEnergyLifecycle)
    assert not isinstance(adapter._energy, InMemoryEnergyLifecycle)


def test_graph_production_branch_calls_port() -> None:
    port = _FakePort(
        DocumentationExecutionOutcome(
            outcome=WorkerOutcome.SUCCESS, attempt_ref="att-9", evidence_refs=("ref:1",)
        )
    )
    state = {
        "workflow_run_id": "run-1",
        "task_id": "task-1",
        "proposal_ref": "p/ref",
        "proposal_digest": "pdigest",
        "approval_ref": "appr-1",
    }
    delta = _execute_documentation(port, state, "run-1")  # type: ignore[arg-type]

    assert port.calls == 1
    assert delta["phase"] == PHASE_VALIDATE
    assert delta["execution_attempt_ref"] == "att-9"
    assert delta["action_intent"]["last_outcome"] == "success"  # type: ignore[index]
    assert "ref:1" in delta["evidence_refs"]  # type: ignore[operator]


def test_graph_production_branch_fails_closed_without_proposal() -> None:
    port = _FakePort(DocumentationExecutionOutcome(outcome=WorkerOutcome.SUCCESS, attempt_ref="x"))
    state = {"workflow_run_id": "run-1", "task_id": "task-1"}  # no proposal authority
    delta = _execute_documentation(port, state, "run-1")  # type: ignore[arg-type]

    assert port.calls == 0  # provider never reached
    assert delta["phase"] == PHASE_FAILED
    assert delta["error_summary"] == "missing_proposal_authority"
