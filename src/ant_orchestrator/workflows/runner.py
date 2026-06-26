"""WorkflowRunner — compile, durable invoke, inspect (PHASE_4_PLAN C.4/CP3).

Owns the checkpointer lifecycle per command and returns framework-neutral results to
the application layer (no LangGraph types leak out). The runner does NOT create
approvals, write Task/WorkflowRun, build ResumeOperations, run Pause/Completion
finalizers, render CLI, or resolve human decisions — those belong to CP4+.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.application.ports.worker import WorkerExecutionPort
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.errors import AntError
from ant_orchestrator.workflows.checkpointer import open_checkpointer
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.graph import build_workflow_graph
from ant_orchestrator.workflows.state import (
    GraphState,
    SchemaCompatibility,
    assert_json_safe,
    check_schema_version,
)

_DURABILITY_SYNC = "sync"


class WorkflowVersionError(AntError):
    """A version guard rejected an invoke/resume (fail-closed)."""


class GraphStateSchemaMismatch(WorkflowVersionError):
    """The graph-state schema version is not the one this code supports."""


class WorkflowDefinitionMismatch(WorkflowVersionError):
    """The run's workflow-definition version is incompatible with this topology."""


@dataclass(frozen=True, slots=True)
class WorkflowInvokeResult:
    """Framework-neutral result of an invoke (no LangGraph types)."""

    final_state: dict[str, object]
    reached_end: bool
    final_outcome: str | None


@dataclass(frozen=True, slots=True)
class StateSummary:
    """A framework-neutral snapshot summary (values + pending next nodes)."""

    values: dict[str, object]
    next_nodes: tuple[str, ...]


class WorkflowRunner:
    """Compiles the graph against a durable checkpointer and runs it synchronously."""

    def __init__(
        self,
        *,
        worker: WorkerExecutionPort,
        policy: DecisionGatePolicy,
        checkpoint_db_path: Path,
        definition_version: int = WORKFLOW_DEFINITION_VERSION,
    ) -> None:
        self._worker = worker
        self._policy = policy
        self._path = checkpoint_db_path
        self._definition_version = definition_version

    def check_definition_version(self, run_definition_version: int) -> None:
        """Fail closed if a run was created under a different graph topology version."""
        if run_definition_version != self._definition_version:
            raise WorkflowDefinitionMismatch(
                f"run definition version {run_definition_version} != {self._definition_version}"
            )

    def invoke(self, initial_state: GraphState, *, thread_id: str) -> WorkflowInvokeResult:
        """Invoke from the initial state with explicit synchronous durability.

        The state is validated JSON-safe (CP2 layer) *and* serialized by the no-pickle
        checkpoint serializer (CP3 layer) — the two defences are complementary.
        """
        self._ensure_schema(initial_state)
        assert_json_safe(initial_state)
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = build_workflow_graph(self._worker, self._policy).compile(checkpointer=saver)
            values = app.invoke(dict(initial_state), config=config, durability=_DURABILITY_SYNC)
            snapshot = app.get_state(config)
            return WorkflowInvokeResult(
                final_state=dict(values),
                reached_end=len(snapshot.next) == 0,
                final_outcome=_as_opt_str(values.get("final_outcome")),
            )

    def latest_state(self, thread_id: str) -> StateSummary:
        """Read the latest durable snapshot (opens a fresh connection)."""
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = build_workflow_graph(self._worker, self._policy).compile(checkpointer=saver)
            snapshot = app.get_state(config)
            return StateSummary(values=dict(snapshot.values), next_nodes=tuple(snapshot.next))

    def state_history(self, thread_id: str) -> list[StateSummary]:
        """Return the full super-step history (diagnostic/test use)."""
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = build_workflow_graph(self._worker, self._policy).compile(checkpointer=saver)
            return [
                StateSummary(values=dict(s.values), next_nodes=tuple(s.next))
                for s in app.get_state_history(config)
            ]

    def _ensure_schema(self, state: Mapping[str, object]) -> None:
        if check_schema_version(state) is not SchemaCompatibility.COMPATIBLE:
            raise GraphStateSchemaMismatch(
                f"unsupported graph_state_schema_version: {state.get('graph_state_schema_version')}"
            )

    @staticmethod
    def _config(thread_id: str) -> dict[str, object]:
        return {"configurable": {"thread_id": thread_id}}


def _as_opt_str(value: object) -> str | None:
    return value if isinstance(value, str) else None
