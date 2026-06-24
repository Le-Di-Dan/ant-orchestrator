"""Provider-neutral cloud LLM adapter backed by LiteLLM (CP3).

Implements the neutral ``LLMAdapter`` async contract. Provider/model/base URL come
from a :class:`ModelEndpointConfig`; the API key comes from a ``SecretProvider``.
LiteLLM is reached only through an injected :class:`LiteLLMCompletionClient` seam,
so unit tests run without network or real secrets. No LiteLLM/OpenAI type is exposed
on the public surface.

OpenAI is the bootstrap provider; the class stays provider-neutral — adding another
cloud provider means extending ``_SECRET_ENV_BY_PROVIDER``, not changing the contract.
"""

from __future__ import annotations

import asyncio
from time import perf_counter

from ant_orchestrator.adapters.adapter_log import log_failure, log_success
from ant_orchestrator.adapters.litellm_client import (
    LiteLLMCompletionClient,
    LiteLLMSdkClient,
)
from ant_orchestrator.adapters.litellm_errors import map_litellm_error
from ant_orchestrator.adapters.litellm_mapping import (
    build_litellm_model_id,
    normalize_response,
    to_completion_payload,
)
from ant_orchestrator.application.ports.llm import (
    AdapterCapabilities,
    AdapterIdentity,
    LLMRequest,
    LLMResponse,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterError,
    AdapterInvalidRequestError,
)
from ant_orchestrator.application.ports.secrets import SecretProvider
from ant_orchestrator.config.models import ModelEndpointConfig
from ant_orchestrator.config.timeout import resolve_timeout

# Cloud providers implemented in Phase 2, mapped to their secret env name.
_SECRET_ENV_BY_PROVIDER = {"openai": "OPENAI_API_KEY"}


class LiteLLMCloudAdapter:
    """Calls a cloud model through LiteLLM behind the neutral ``LLMAdapter`` contract."""

    def __init__(
        self,
        endpoint: ModelEndpointConfig,
        secrets: SecretProvider,
        *,
        client: LiteLLMCompletionClient | None = None,
    ) -> None:
        if endpoint.provider not in _SECRET_ENV_BY_PROVIDER:
            raise AdapterInvalidRequestError(
                "unsupported cloud provider", provider=endpoint.provider, model=endpoint.model
            )
        # Fail fast: compose the model id once at construction.
        self._model_id = build_litellm_model_id(endpoint.provider, endpoint.model)
        self._endpoint = endpoint
        self._secrets = secrets
        self._client: LiteLLMCompletionClient = client if client is not None else LiteLLMSdkClient()
        self._secret_name = _SECRET_ENV_BY_PROVIDER[endpoint.provider]

    @property
    def identity(self) -> AdapterIdentity:
        return AdapterIdentity(provider=self._endpoint.provider)

    @property
    def capabilities(self) -> AdapterCapabilities:
        return AdapterCapabilities(is_local=False)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        provider, model = self._endpoint.provider, self._endpoint.model
        timeout = resolve_timeout(request.timeout_seconds, self._endpoint.timeout_seconds)
        api_key = self._secrets.get(self._secret_name)
        if not api_key:
            raise AdapterAuthenticationError(
                "missing API credential", provider=provider, model=model
            )
        payload = to_completion_payload(
            request,
            model_id=self._model_id,
            api_key=api_key,
            base_url=self._endpoint.base_url,
            timeout=timeout,
        )
        started = perf_counter()
        try:
            raw = await self._client.acompletion(payload)
            response = normalize_response(raw, provider=provider, model=model)
        except asyncio.CancelledError:
            raise
        except AdapterError as exc:
            log_failure(
                provider=provider,
                model=model,
                duration_ms=_elapsed_ms(started),
                error_code=exc.code.value,
                retryable=exc.retryable,
            )
            raise
        except Exception as exc:
            error = map_litellm_error(exc, provider=provider, model=model)
            log_failure(
                provider=provider,
                model=model,
                duration_ms=_elapsed_ms(started),
                error_code=error.code.value,
                retryable=error.retryable,
            )
            raise error from None
        log_success(
            provider=provider,
            model=model,
            duration_ms=_elapsed_ms(started),
            usage=response.usage,
            finish_reason=response.finish_reason.value,
        )
        return response


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0
