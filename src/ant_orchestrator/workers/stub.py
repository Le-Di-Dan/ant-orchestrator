"""Deterministic worker stub adapter (PHASE_4_PLAN C.11).

A no-op worker: no network, no shell, no filesystem writes, no model calls, no
secrets. It returns a bounded, sanitized SUCCESS result derived only from the
logical action id — behaviour is never steered by free-form title/description text.
Same structured input always yields the same outcome.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.worker import (
    MAX_WORKER_DETAIL_CHARS,
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)


class DeterministicStubAdapter:
    """A deterministic, side-effect-free implementation of ``WorkerExecutionPort``."""

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        detail = f"stub-executed:{intent.logical_action_id}"[:MAX_WORKER_DETAIL_CHARS]
        return WorkerExecutionResult(outcome=WorkerOutcome.SUCCESS, detail=detail)
