"""SecretProvider port: the single boundary for reading secrets (PHASE_2_PLAN §5).

Adapters never read ``os.environ`` directly; they depend on this port so secret
sourcing is injectable and testable. Semantics are deliberately simple:

- A missing name returns ``None``.
- A name present but empty returns ``None``.
- A non-empty value is returned unchanged (no stripping/transformation).

Absence is *not* an error, so there is no dedicated "missing secret" exception.
Turning a missing cloud secret into an ``AdapterAuthenticationError`` is the
adapter/factory's responsibility (CP3/CP6), not this port's.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class SecretProvider(Protocol):
    """Resolves a named secret, returning ``None`` when it is unavailable."""

    def get(self, name: str) -> str | None:
        """Return the secret value for ``name``, or ``None`` if unavailable."""
        ...
