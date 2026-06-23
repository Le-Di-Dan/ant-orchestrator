"""Neutral, provider-agnostic LLM adapter error taxonomy (PHASE_2_PLAN §5).

Every error derives from :class:`ant_orchestrator.errors.AntError` and carries
only *sanitized* structured metadata: a stable ``code``, a ``retryable`` hint and
optional provider/model identifiers. An adapter error must never embed secrets,
full prompts, full responses or raw provider exceptions in its public message or
representation — concrete adapters (CP3+) are responsible for sanitizing before
raising.
"""

from __future__ import annotations

from enum import Enum
from typing import ClassVar

from ant_orchestrator.errors import AntError


class AdapterErrorCode(Enum):
    """Stable, neutral error codes (no provider-specific strings)."""

    UNKNOWN = "adapter.unknown"
    TIMEOUT = "adapter.timeout"
    CONNECTION = "adapter.connection"
    RATE_LIMIT = "adapter.rate_limit"
    AUTHENTICATION = "adapter.authentication"
    INVALID_REQUEST = "adapter.invalid_request"
    PROVIDER = "adapter.provider"
    RESPONSE = "adapter.response"


class AdapterError(AntError):
    """Base class for every adapter failure.

    ``retryable`` defaults to the class-level :attr:`default_retryable` but a
    caller may override it per-instance (notably for :class:`AdapterProviderError`,
    whose retryability depends on the root cause).
    """

    code: ClassVar[AdapterErrorCode] = AdapterErrorCode.UNKNOWN
    default_retryable: ClassVar[bool] = False

    def __init__(
        self,
        message: str = "",
        *,
        provider: str | None = None,
        model: str | None = None,
        retryable: bool | None = None,
    ) -> None:
        self.provider = provider
        self.model = model
        self.retryable = self.default_retryable if retryable is None else retryable
        super().__init__(message)

    def __repr__(self) -> str:
        # Deliberately excludes the message payload so accidental sensitive text
        # in a subclass message is never echoed through ``repr``.
        return (
            f"{type(self).__name__}(code={self.code.value!r}, "
            f"retryable={self.retryable}, provider={self.provider!r}, "
            f"model={self.model!r})"
        )


class AdapterTimeoutError(AdapterError):
    """The provider did not respond within the resolved timeout."""

    code = AdapterErrorCode.TIMEOUT
    default_retryable = True


class AdapterConnectionError(AdapterError):
    """The provider/endpoint could not be reached (e.g. local Ollama down)."""

    code = AdapterErrorCode.CONNECTION
    default_retryable = True


class AdapterRateLimitError(AdapterError):
    """The provider rejected the call due to rate/quota limits."""

    code = AdapterErrorCode.RATE_LIMIT
    default_retryable = True


class AdapterAuthenticationError(AdapterError):
    """Authentication/authorization failed (missing or invalid secret).

    Intentionally NOT a subclass of :class:`AdapterInvalidRequestError`.
    """

    code = AdapterErrorCode.AUTHENTICATION
    default_retryable = False


class AdapterInvalidRequestError(AdapterError):
    """The request was malformed or unsupported (including missing model config)."""

    code = AdapterErrorCode.INVALID_REQUEST
    default_retryable = False


class AdapterProviderError(AdapterError):
    """The provider returned a server-side error.

    ``default_retryable`` is conservatively ``False``: callers must set
    ``retryable=True`` explicitly only when the cause is known to be transient.
    """

    code = AdapterErrorCode.PROVIDER
    default_retryable = False


class AdapterResponseError(AdapterError):
    """The provider response was missing/invalid and could not be normalized."""

    code = AdapterErrorCode.RESPONSE
    default_retryable = False
