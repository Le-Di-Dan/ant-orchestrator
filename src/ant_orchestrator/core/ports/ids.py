"""IdGenerator port: identity creation is injectable so tests are deterministic
(PHASE_1_PLAN §18, D08). Production uses UUID4."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class IdGenerator(Protocol):
    """Generates opaque unique identifier strings."""

    def new_id(self) -> str:
        """Return a fresh unique identifier."""
        ...
