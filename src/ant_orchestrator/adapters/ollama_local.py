"""Local Ollama LLM adapter backed by the shared LiteLLM infrastructure (CP4).

A separate class from the cloud adapter because local deployment differs: no
credential, a required ``base_url``, and ``is_local=True``. It reuses the shared
seam, payload mapping, model-id helper, response/usage/error normalization,
logging and timeout resolver — no provider logic is duplicated. No Ollama SDK and
no HTTP client are imported; everything goes through LiteLLM.
"""

from __future__ import annotations

from ant_orchestrator.adapters.litellm_client import (
    LiteLLMCompletionClient,
    LiteLLMSdkClient,
)
from ant_orchestrator.adapters.litellm_invoke import run_completion
from ant_orchestrator.adapters.litellm_mapping import (
    build_litellm_model_id,
    to_completion_payload,
)
from ant_orchestrator.application.ports.llm import (
    AdapterCapabilities,
    AdapterIdentity,
    LLMRequest,
    LLMResponse,
)
from ant_orchestrator.application.ports.llm_errors import AdapterInvalidRequestError
from ant_orchestrator.config.models import ModelEndpointConfig
from ant_orchestrator.config.timeout import resolve_timeout

_OLLAMA_PROVIDER = "ollama"


class OllamaAdapter:
    """Calls a local Ollama model through the shared LiteLLM seam (no credential)."""

    def __init__(
        self,
        endpoint: ModelEndpointConfig,
        *,
        client: LiteLLMCompletionClient | None = None,
    ) -> None:
        if endpoint.provider != _OLLAMA_PROVIDER:
            raise AdapterInvalidRequestError(
                "OllamaAdapter requires provider 'ollama'",
                provider=endpoint.provider,
                model=endpoint.model,
            )
        if endpoint.base_url is None:
            raise AdapterInvalidRequestError(
                "Ollama endpoint requires an explicit base_url",
                provider=endpoint.provider,
                model=endpoint.model,
            )
        # Fail fast: compose the model id once at construction.
        self._model_id = build_litellm_model_id(endpoint.provider, endpoint.model)
        self._endpoint = endpoint
        self._base_url: str = endpoint.base_url
        self._client: LiteLLMCompletionClient = client if client is not None else LiteLLMSdkClient()

    @property
    def identity(self) -> AdapterIdentity:
        return AdapterIdentity(provider=self._endpoint.provider)

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(is_local=True)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        provider, model = self._endpoint.provider, self._endpoint.model
        timeout = resolve_timeout(request.timeout_seconds, self._endpoint.timeout_seconds)
        payload = to_completion_payload(
            request,
            model_id=self._model_id,
            timeout=timeout,
            base_url=self._base_url,
        )
        return await run_completion(self._client, payload, provider=provider, model=model)
