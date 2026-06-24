"""Test doubles for the LiteLLM seam (CP3).

A fake completion client (records payloads, returns scripted raw responses or
raises a scripted exception) plus duck-typed raw-response builders. Never imports
LiteLLM, so adapter/mapping tests stay deterministic and offline.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any

_UNSET: Any = object()


def make_usage(
    prompt_tokens: object = None,
    completion_tokens: object = None,
    total_tokens: object = None,
) -> SimpleNamespace:
    """Build a duck-typed usage object."""
    return SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def make_raw_response(
    *,
    content: object = "hello world",
    finish_reason: object = "stop",
    usage: Any = _UNSET,
    choices: Any = _UNSET,
    model: str = "example-model",
) -> SimpleNamespace:
    """Build a duck-typed raw provider response (like LiteLLM's ModelResponse)."""
    if choices is _UNSET:
        choices = [
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    if usage is _UNSET:
        usage = make_usage(10, 20, 30)
    return SimpleNamespace(choices=choices, usage=usage, model=model)


class FakeLiteLLMClient:
    """Implements the LiteLLMCompletionClient seam without any SDK."""

    def __init__(
        self,
        *,
        responses: list[Any] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._responses = list(responses) if responses is not None else []
        self._error = error
        self.payloads: list[dict[str, object]] = []

    async def acompletion(self, payload: Mapping[str, object]) -> Any:
        self.payloads.append(dict(payload))
        if self._error is not None:
            raise self._error
        if self._responses:
            return self._responses.pop(0)
        return make_raw_response()
