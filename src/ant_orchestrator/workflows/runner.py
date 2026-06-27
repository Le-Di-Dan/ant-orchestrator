"""WorkflowRunner — compile, durable invoke/resume, inspect (PHASE_4_PLAN C.4).

Owns the checkpointer lifecycle per command and returns framework-neutral results
to the application layer (no LangGraph types leak out). The runner does NOT create
approvals, write Task/WorkflowRun, build ResumeOperations, run Pause/Completion
finalizers, render CLI, or resolve human decisions — those belong to the application
services. It only drives the graph and reports interrupts/snapshots.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from langgraph.types import Command

from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionPort,
)
from ant_orchestrator.application.ports.worker import WorkerExecutionPort
from ant_orchestrator.application.ports.workflow_runner import (
    GraphStateSchemaMismatch,
    InterruptView,
    StateSummary,
    WorkflowDefinitionMismatch,
    WorkflowInvokeResult,
    WorkflowRunnerError,
)
from ant_orchestrator.config.constants import WORKFLOW_DEFINITION_VERSION
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from ant_orchestrator.workflows.cancellation_probe import CancellationProbe
from ant_orchestrator.workflows.checkpointer import open_checkpointer
from ant_orchestrator.workflows.decision_gate import DecisionGatePolicy
from ant_orchestrator.workflows.graph import build_workflow_graph
from ant_orchestrator.workflows.state import (
    SchemaCompatibility,
    assert_json_safe,
    check_schema_version,
    new_graph_state,
)

__all__ = [
    "GraphStateSchemaMismatch",
    "StateSummary",
    "WorkflowDefinitionMismatch",
    "WorkflowInvokeResult",
    "WorkflowRunner",
    "WorkflowRunnerError",
]

_DURABILITY_SYNC = "sync"


def _checkpoint_id(snapshot: Any) -> str | None:
    configurable = snapshot.config.get("configurable", {}) if snapshot.config else {}
    value = configurable.get("checkpoint_id")
    return str(value) if value is not None else None


def _interrupt_views(snapshot: Any) -> tuple[InterruptView, ...]:
    views: list[InterruptView] = []
    for item in snapshot.interrupts:
        payload = dict(item.value) if isinstance(item.value, Mapping) else {}
        gate_instance_id = payload.get("gate_instance_id")
        views.append(
            InterruptView(
                langgraph_interrupt_id=str(item.id),
                gate_instance_id=str(gate_instance_id) if gate_instance_id is not None else None,
                payload=payload,
            )
        )
    return tuple(views)


class WorkflowRunner:
    """Compiles the graph against a durable checkpointer and runs it synchronously."""

    def __init__(
        self,
        *,
        worker: WorkerExecutionPort,
        policy: DecisionGatePolicy,
        checkpoint_db_path: Path,
        attempt_orchestrator: AttemptOrchestrator | None = None,
        cancellation_probe: CancellationProbe | None = None,
        definition_version: int = WORKFLOW_DEFINITION_VERSION,
        documentation_execution: DocumentationExecutionPort | None = None,
    ) -> None:
        self._worker = worker
        self._policy = policy
        self._path = checkpoint_db_path
        self._attempt_orchestrator = attempt_orchestrator
        self._cancellation_probe = cancellation_probe
        self._definition_version = definition_version
        self._documentation_execution = documentation_execution

    def _build_app(self, saver: object) -> Any:
        """Compile the graph against ``saver`` with all injected dependencies."""
        return build_workflow_graph(
            self._worker,
            self._policy,
            self._attempt_orchestrator,
            self._cancellation_probe,
            self._documentation_execution,
        ).compile(checkpointer=saver)

    def check_definition_version(self, run_definition_version: int) -> None:
        """Fail closed if a run was created under a different graph topology version."""
        if run_definition_version != self._definition_version:
            raise WorkflowDefinitionMismatch(
                f"run definition version {run_definition_version} != {self._definition_version}"
            )

    def check_state_schema(self, values: Mapping[str, object]) -> None:
        """Fail closed if a durable snapshot's graph-state schema is unsupported.

        A snapshot with no schema field is an *empty* thread (no durable checkpoint
        yet) — not a mismatch — so it is skipped; callers handle the never-invoked
        case separately.
        """
        if values.get("graph_state_schema_version") is None:
            return
        self._ensure_schema(values)

    def build_initial_state(
        self, *, task_id: str, workflow_run_id: str, base_retry_limit: int
    ) -> dict[str, object]:
        """Build a validated JSON-safe initial state for a new run (no LangGraph types)."""
        return dict(
            new_graph_state(
                task_id=task_id, workflow_run_id=workflow_run_id, base_retry_limit=base_retry_limit
            )
        )

    def invoke(
        self, initial_state: Mapping[str, object], *, thread_id: str
    ) -> WorkflowInvokeResult:
        """Invoke from the initial state with explicit synchronous durability.

        The state is validated JSON-safe (CP2 layer) *and* serialized by the no-pickle
        checkpoint serializer (CP3 layer) — the two defences are complementary.
        """
        self._ensure_schema(initial_state)
        assert_json_safe(initial_state)
        return self._drive(dict(initial_state), thread_id=thread_id)

    def resume(self, *, thread_id: str, interrupt_id: str, decision: str) -> WorkflowInvokeResult:
        """Resume a paused graph with an interrupt-specific decision mapping.

        The durable snapshot's graph-state schema is re-validated before driving the
        ``Command`` so a checkpoint written by an incompatible code version fails closed
        instead of resuming into a state this topology no longer understands.
        """
        command = Command(resume={interrupt_id: decision})
        return self._drive(command, thread_id=thread_id, check_schema=True)

    def latest_state(self, thread_id: str) -> StateSummary:
        """Read the latest durable snapshot (opens a fresh connection)."""
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = self._build_app(saver)
            snapshot = app.get_state(config)
            return self._summary(snapshot)

    def state_history(self, thread_id: str) -> list[StateSummary]:
        """Return the full super-step history (diagnostic/test use)."""
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = self._build_app(saver)
            return [self._summary(s) for s in app.get_state_history(config)]

    def _drive(
        self, payload: object, *, thread_id: str, check_schema: bool = False
    ) -> WorkflowInvokeResult:
        config = self._config(thread_id)
        with open_checkpointer(self._path) as saver:
            app = self._build_app(saver)
            if check_schema:
                self._ensure_schema(app.get_state(config).values)
            values = app.invoke(payload, config=config, durability=_DURABILITY_SYNC)
            snapshot = app.get_state(config)
            interrupts = _interrupt_views(snapshot)
            return WorkflowInvokeResult(
                final_state=dict(values),
                reached_end=len(snapshot.next) == 0 and not interrupts,
                final_outcome=_as_opt_str(values.get("final_outcome")),
                checkpoint_id=_checkpoint_id(snapshot),
                interrupt=interrupts[0] if interrupts else None,
            )

    @staticmethod
    def _summary(snapshot: Any) -> StateSummary:
        return StateSummary(
            values=dict(snapshot.values),
            next_nodes=tuple(snapshot.next),
            checkpoint_id=_checkpoint_id(snapshot),
            interrupts=_interrupt_views(snapshot),
        )

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
