"""Clock port: the single source of "now" so time is injectable and tests stay
deterministic (PHASE_1_PLAN §18, D09)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ant_orchestrator.core.domain.value_objects import UtcTimestamp


@runtime_checkable
class Clock(Protocol):
    """Provides the current UTC time."""

    def now(self) -> UtcTimestamp:
        """Return the current instant as a UTC timestamp."""
        ...
