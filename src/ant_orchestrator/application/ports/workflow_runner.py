"""Workflow-runner port — framework-neutral graph driving (PHASE_4_PLAN C.4/§15).

The application layer drives the graph through this port so it never imports
LangGraph. The runner returns sanitized, framework-neutral views: an interrupt is
described by its stable id, gate-instance id and JSON-safe payload — no LangGraph
``Interrupt``/``Command``/``StateSnapshot`` type ever crosses this boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from ant_orchestrator.errors import AntError


class WorkflowRunnerError(AntError):
    """Base class for runner-contract failures (fail-closed)."""


class GraphStateSchemaMismatch(WorkflowRunnerError):
    """The graph-state schema version is not the one this code supports."""


class WorkflowDefinitionMismatch(WorkflowRunnerError):
    """The run's workflow-definition version is incompatible with this topology."""


@dataclass(frozen=True, slots=True)
class InterruptView:
    """A sanitized view of one pending interrupt (PHASE_4_PLAN C.5/PATCH #2)."""

    langgraph_interrupt_id: str
    gate_instance_id: str | None
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class WorkflowInvokeResult:
    """Framework-neutral result of an invoke/resume (no LangGraph types)."""

    final_state: dict[str, object]
    reached_end: bool
    final_outcome: str | None
    checkpoint_id: str | None = None
    interrupt: InterruptView | None = None


@dataclass(frozen=True, slots=True)
class StateSummary:
    """A framework-neutral snapshot summary (values + pending nodes + interrupts)."""

    values: dict[str, object]
    next_nodes: tuple[str, ...]
    checkpoint_id: str | None = None
    interrupts: tuple[InterruptView, ...] = ()

    @property
    def is_interrupted(self) -> bool:
        """True when the snapshot is paused on at least one interrupt."""
        return len(self.interrupts) > 0


class WorkflowRunnerPort(Protocol):
    """Durable graph driving over a checkpointer (implemented in ``workflows``)."""

    def check_definition_version(self, run_definition_version: int) -> None:
        """Raise ``WorkflowDefinitionMismatch`` if a run predates this topology."""
        ...

    def build_initial_state(
        self, *, task_id: str, workflow_run_id: str, base_retry_limit: int
    ) -> dict[str, object]:
        """Build a JSON-safe initial graph state for a new workflow run."""
        ...

    def invoke(
        self, initial_state: Mapping[str, object], *, thread_id: str
    ) -> WorkflowInvokeResult:
        """Invoke from an initial state with synchronous durability."""
        ...

    def resume(self, *, thread_id: str, interrupt_id: str, decision: str) -> WorkflowInvokeResult:
        """Resume a paused graph with an interrupt-specific decision."""
        ...

    def latest_state(self, thread_id: str) -> StateSummary:
        """Read the latest durable snapshot (interrupts + checkpoint id)."""
        ...
