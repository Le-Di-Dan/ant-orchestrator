"""Map LiteLLM/OpenAI exceptions to the neutral adapter error taxonomy (CP3).

Mapping is by exception *class* (and HTTP status for the generic case), never by
parsing message strings. Public errors carry only sanitized metadata
(provider/model/code/retryable) and are raised ``from None`` so no raw provider
text, body, prompt or secret leaks through chaining. ``litellm`` is imported lazily
so this module is cheap to import and is only pulled in when an error is mapped.
"""

from __future__ import annotations

from typing import Any

from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterConnectionError,
    AdapterError,
    AdapterInvalidRequestError,
    AdapterProviderError,
    AdapterRateLimitError,
    AdapterTimeoutError,
)

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})


def map_litellm_error(exc: Exception, *, provider: str, model: str) -> AdapterError:
    """Return the neutral adapter error for a LiteLLM exception (no raw text)."""
    import litellm

    def build(
        cls: type[AdapterError], message: str, *, retryable: bool | None = None
    ) -> AdapterError:
        return cls(message, provider=provider, model=model, retryable=retryable)

    if isinstance(exc, litellm.AuthenticationError | litellm.PermissionDeniedError):
        return build(AdapterAuthenticationError, "authentication failed")
    if isinstance(exc, litellm.RateLimitError):
        return build(AdapterRateLimitError, "rate limited")
    # Timeout subclasses APIConnectionError, so it must be checked first.
    if isinstance(exc, litellm.Timeout):
        return build(AdapterTimeoutError, "request timed out")
    if isinstance(exc, litellm.APIConnectionError):
        return build(AdapterConnectionError, "connection error")
    if isinstance(
        exc, litellm.BadRequestError | litellm.NotFoundError | litellm.UnprocessableEntityError
    ):
        return build(AdapterInvalidRequestError, "invalid request")
    if isinstance(exc, litellm.ServiceUnavailableError | litellm.InternalServerError):
        return build(AdapterProviderError, "provider error", retryable=True)
    if isinstance(exc, litellm.APIError):
        status = _status_code(exc)
        retryable = status in _RETRYABLE_STATUS
        return build(AdapterProviderError, "provider error", retryable=retryable)
    return build(AdapterProviderError, "provider error", retryable=False)


def _status_code(exc: Any) -> int | None:
    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None
