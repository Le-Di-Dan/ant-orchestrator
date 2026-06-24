"""Tests for LiteLLM exception -> neutral error mapping (CP3; imports LiteLLM)."""

from __future__ import annotations

import httpx
import litellm

from ant_orchestrator.adapters.litellm_errors import map_litellm_error
from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterConnectionError,
    AdapterError,
    AdapterInvalidRequestError,
    AdapterProviderError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)

_REQ = httpx.Request("POST", "http://provider.invalid")


def _auth() -> Exception:
    return litellm.AuthenticationError(message="x", llm_provider="openai", model="m")


def _permission() -> Exception:
    return litellm.PermissionDeniedError(
        message="x", llm_provider="openai", model="m", response=httpx.Response(403, request=_REQ)
    )


def _cases() -> list[tuple[Exception, type[AdapterError], bool]]:
    return [
        (_auth(), AdapterAuthenticationError, False),
        (_permission(), AdapterAuthenticationError, False),
        (
            litellm.RateLimitError(message="x", llm_provider="openai", model="m"),
            AdapterRateLimitError,
            True,
        ),
        (litellm.Timeout(message="x", model="m", llm_provider="openai"), AdapterTimeoutError, True),
        (
            litellm.APIConnectionError(message="x", llm_provider="openai", model="m"),
            AdapterConnectionError,
            True,
        ),
        (
            litellm.BadRequestError(message="x", model="m", llm_provider="openai"),
            AdapterInvalidRequestError,
            False,
        ),
        (
            litellm.ContextWindowExceededError(message="x", model="m", llm_provider="openai"),
            AdapterInvalidRequestError,
            False,
        ),
        (
            litellm.ServiceUnavailableError(message="x", llm_provider="openai", model="m"),
            AdapterProviderError,
            True,
        ),
        (
            litellm.InternalServerError(message="x", llm_provider="openai", model="m"),
            AdapterProviderError,
            True,
        ),
        (
            litellm.APIError(status_code=500, message="x", llm_provider="openai", model="m"),
            AdapterProviderError,
            True,
        ),
        (
            litellm.APIError(status_code=400, message="x", llm_provider="openai", model="m"),
            AdapterProviderError,
            False,
        ),
        (ValueError("totally unknown"), AdapterProviderError, False),
    ]


def test_error_mapping() -> None:
    for exc, expected_cls, retryable in _cases():
        mapped = map_litellm_error(exc, provider="openai", model="m")
        assert isinstance(mapped, expected_cls), f"{type(exc).__name__} -> {type(mapped).__name__}"
        assert mapped.retryable is retryable
        assert mapped.provider == "openai"
        assert mapped.model == "m"


def test_unknown_provider_error_not_retryable_by_default() -> None:
    mapped = map_litellm_error(ValueError("boom"), provider="openai", model="m")
    assert mapped.retryable is False


def test_mapped_error_does_not_leak_raw_provider_text() -> None:
    secret_text = "SECRET-LEAK-123 api_key=sk-real-deadbeef"
    exc = litellm.AuthenticationError(message=secret_text, llm_provider="openai", model="m")
    mapped = map_litellm_error(exc, provider="openai", model="m")
    assert "SECRET-LEAK-123" not in str(mapped)
    assert "sk-real-deadbeef" not in str(mapped)
    assert "SECRET-LEAK-123" not in repr(mapped)
