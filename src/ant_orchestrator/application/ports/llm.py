"""Provider-neutral, asynchronous LLM adapter contract (PHASE_2_PLAN §4/§5).

This is the public application boundary every model adapter implements. It is
intentionally free of any provider/SDK type (LiteLLM, OpenAI, Ollama). Fields are
limited to what Phase 2 needs; speculative Phase 3–6 concepts (context package,
streaming, retry, monetary cost, persistence) are deliberately excluded.

The contract is ``async`` because model invocation is I/O-bound; synchronous entry
points bridge with ``asyncio.run`` at their own boundary, never here.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


class MessageRole(Enum):
    """Role of a conversation message."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class FinishReason(Enum):
    """Neutral reason the model stopped generating."""

    STOP = "stop"
    LENGTH = "length"
    CONTENT_FILTER = "content_filter"
    ERROR = "error"
    UNKNOWN = "unknown"


class UsageStatus(Enum):
    """Whether token usage was measured, estimated or simply not provided."""

    MEASURED = "measured"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Token usage for a single invocation, representing missing data honestly.

    Valid field combinations (no ambiguous "when available" rules):

    - ``UNAVAILABLE``: ``tokens_in``/``tokens_out``/``tokens_total`` are all
      ``None`` (never zero-filled).
    - ``MEASURED`` / ``ESTIMATED``: ``tokens_in`` and ``tokens_out`` are both
      present; if ``tokens_total`` is present it must equal their sum.

    Negative counts are rejected by :class:`TokenCount`. No monetary cost.
    """

    status: UsageStatus
    tokens_in: TokenCount | None = None
    tokens_out: TokenCount | None = None
    tokens_total: TokenCount | None = None

    def __post_init__(self) -> None:
        if self.status is UsageStatus.UNAVAILABLE:
            if (
                self.tokens_in is not None
                or self.tokens_out is not None
                or self.tokens_total is not None
            ):
                raise InvariantViolation("UNAVAILABLE usage must carry no token counts")
            return
        if self.tokens_in is None or self.tokens_out is None:
            raise InvariantViolation(
                f"{self.status.value} usage requires both tokens_in and tokens_out"
            )
        if self.tokens_total is not None:
            expected = self.tokens_in.value + self.tokens_out.value
            if self.tokens_total.value != expected:
                raise InvariantViolation("tokens_total must equal tokens_in + tokens_out")

    @classmethod
    def measured(cls, tokens_in: int, tokens_out: int) -> ModelUsage:
        """Build a MEASURED usage with a consistent total."""
        return cls(
            UsageStatus.MEASURED,
            TokenCount(tokens_in),
            TokenCount(tokens_out),
            TokenCount(tokens_in + tokens_out),
        )

    @classmethod
    def unavailable(cls) -> ModelUsage:
        """Build an UNAVAILABLE usage (no token counts)."""
        return cls(UsageStatus.UNAVAILABLE)


@dataclass(frozen=True, slots=True)
class LLMMessage:
    """A single conversation message."""

    role: MessageRole
    content: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """An immutable request for a single completion.

    ``model`` is supplied by the caller/config — never hard-coded in an adapter.
    ``timeout_seconds`` is an optional per-request override; the full precedence
    resolution lives in the config/timeout layer (CP2), not in this DTO.
    """

    model: str
    messages: tuple[LLMMessage, ...] = ()
    system_prompt: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    timeout_seconds: float | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model:
            raise InvariantViolation("LLMRequest.model must be a non-empty string")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """An immutable completion result with normalized usage."""

    text: str
    provider: str
    model: str
    usage: ModelUsage
    finish_reason: FinishReason = FinishReason.STOP

    def __post_init__(self) -> None:
        if not self.provider:
            raise InvariantViolation("LLMResponse.provider must be a non-empty string")
        if not self.model:
            raise InvariantViolation("LLMResponse.model must be a non-empty string")


@dataclass(frozen=True, slots=True)
class AdapterIdentity:
    """Stable identity of an adapter (model is per-request, so not pinned here)."""

    provider: str

    def __post_init__(self) -> None:
        if not self.provider:
            raise InvariantViolation("AdapterIdentity.provider must be a non-empty string")


@dataclass(frozen=True, slots=True)
class AdapterCapabilities:
    """Declarative capability metadata used for selection (no monetary cost)."""

    is_local: bool
    supports_system_prompt: bool = True
    max_context_tokens: int | None = None


@runtime_checkable
class LLMAdapter(Protocol):
    """Async, provider-neutral interface every model adapter implements."""

    @property
    def identity(self) -> AdapterIdentity:
        """Return the adapter's stable identity (provider)."""
        ...

    @property
    def capabilities(self) -> AdapterCapabilities:
        """Return declarative capability metadata."""
        ...

    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Run a single completion, returning a normalized response.

        Raises a subclass of
        :class:`ant_orchestrator.application.ports.llm_errors.AdapterError`
        on failure.
        """
        ...
