"""FakeLLMAdapter — a deterministic in-memory ``LLMAdapter`` test double (CP1).

Test-only: lives outside ``src/`` and must never be imported by production code
nor import any provider SDK (LiteLLM/OpenAI/Ollama). It records received requests
for assertions and can be scripted to return responses or raise structured errors.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.llm import (
    AdapterCapabilities,
    AdapterIdentity,
    FinishReason,
    LLMRequest,
    LLMResponse,
    ModelUsage,
)
from ant_orchestrator.application.ports.llm_errors import AdapterError

_DEFAULT_PROVIDER = "fake"
_DEFAULT_MODEL = "fake-model"


class FakeLLMAdapter:
    """A scriptable async LLM adapter.

    Args:
        responses: queued responses returned in order by ``complete``.
        error: if set, ``complete`` raises it instead of returning.
        identity / capabilities: overrides for the adapter metadata.
    """

    def __init__(
        self,
        *,
        responses: list[LLMResponse] | None = None,
        error: AdapterError | None = None,
        identity: AdapterIdentity | None = None,
        capabilities: AdapterCapabilities | None = None,
    ) -> None:
        self._responses = list(responses) if responses is not None else []
        self._error = error
        self._identity = identity or AdapterIdentity(provider=_DEFAULT_PROVIDER)
        self._capabilities = capabilities or AdapterCapabilities(is_local=True)
        self.received: list[LLMRequest] = []

    @property
    def identity(self) -> AdapterIdentity:
        return self._identity

    @property
    def capabilities(self) -> AdapterCapabilities:
        return self._capabilities

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.received.append(request)
        if self._error is not None:
            raise self._error
        if self._responses:
            return self._responses.pop(0)
        return LLMResponse(
            text="fake-response",
            provider=self._identity.provider,
            model=_DEFAULT_MODEL,
            usage=ModelUsage.measured(tokens_in=1, tokens_out=1),
            finish_reason=FinishReason.STOP,
        )


def fake_with_error(error: AdapterError) -> FakeLLMAdapter:
    """Build a fake whose ``complete`` always raises ``error``."""
    return FakeLLMAdapter(error=error)


def fake_with_response(response: LLMResponse) -> FakeLLMAdapter:
    """Build a fake whose ``complete`` returns ``response`` once."""
    return FakeLLMAdapter(responses=[response])
