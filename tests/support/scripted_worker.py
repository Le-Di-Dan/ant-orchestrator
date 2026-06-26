"""Scripted worker stub (test-only) — emits an explicit outcome sequence.

Outcomes are taken in order from a script; nothing is inferred from free-form text.
When the script is exhausted it raises ``StubScriptExhausted`` unless an explicit
fallback outcome was provided — it never silently succeeds.
"""

from __future__ import annotations

from collections.abc import Sequence

from ant_orchestrator.application.ports.worker import (
    WorkerActionIntent,
    WorkerExecutionResult,
    WorkerOutcome,
)


class StubScriptExhausted(RuntimeError):
    """The scripted worker ran out of outcomes and had no fallback."""


class ScriptedStubAdapter:
    """A WorkerExecutionPort test double that replays a fixed outcome sequence."""

    def __init__(
        self,
        outcomes: Sequence[WorkerOutcome],
        *,
        fallback: WorkerOutcome | None = None,
    ) -> None:
        self._outcomes = list(outcomes)
        self._fallback = fallback
        self._index = 0

    def execute(self, intent: WorkerActionIntent) -> WorkerExecutionResult:
        if self._index < len(self._outcomes):
            outcome = self._outcomes[self._index]
            self._index += 1
        elif self._fallback is not None:
            outcome = self._fallback
        else:
            raise StubScriptExhausted("scripted worker outcomes exhausted with no fallback")
        return WorkerExecutionResult(outcome=outcome, detail=f"scripted:{intent.logical_action_id}")
