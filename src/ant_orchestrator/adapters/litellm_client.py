"""Internal LiteLLM SDK seam (infrastructure only, CP3).

A tiny boundary whose sole responsibility is "call LiteLLM async". It exists so
the cloud adapter can be unit-tested with an injected fake instead of monkeypatching
LiteLLM global state. It is NOT an application port and must never be imported by
core/application/config. ``litellm`` is imported lazily so importing this module
(and the adapter) does not pay the heavy SDK import cost until a real call is made.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol


class LiteLLMCompletionClient(Protocol):
    """Seam: runs one async completion given an explicit, pre-built payload."""

    async def acompletion(self, payload: Mapping[str, object]) -> Any:
        """Return the raw provider response object (opaque to callers)."""
        ...


class LiteLLMSdkClient:
    """Production seam that forwards to ``litellm.acompletion``."""

    async def acompletion(self, payload: Mapping[str, object]) -> Any:
        import litellm

        return await litellm.acompletion(**payload)
