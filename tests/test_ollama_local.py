"""Behavioural tests for OllamaAdapter (CP4; fake seam, no Ollama needed)."""

from __future__ import annotations

import asyncio
import logging

import litellm
import pytest

from ant_orchestrator.adapters.ollama_local import OllamaAdapter
from ant_orchestrator.application.ports.llm import (
    LLMMessage,
    LLMRequest,
    MessageRole,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterConnectionError,
    AdapterInvalidRequestError,
    AdapterResponseError,
    AdapterTimeoutError,
)
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.support.fake_litellm import FakeLiteLLMClient, make_raw_response

_BASE = "http://localhost:11434"
_LOGGER = "ant_orchestrator.adapters.llm"


def _endpoint(
    *,
    provider: str = "ollama",
    model: str = "example-model",
    base_url: str | None = _BASE,
    timeout_seconds: float | None = None,
) -> ModelEndpointConfig:
    return ModelEndpointConfig(
        provider=provider, model=model, base_url=base_url, timeout_seconds=timeout_seconds
    )


def _adapter(
    *, client: FakeLiteLLMClient | None = None, endpoint: ModelEndpointConfig | None = None
) -> OllamaAdapter:
    return OllamaAdapter(endpoint or _endpoint(), client=client or FakeLiteLLMClient())


def _request(*, timeout: float | None = None) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "hi"),),
        system_prompt="DO-NOT-LOG-PROMPT",
        timeout_seconds=timeout,
    )


# --- construction / identity --------------------------------------------------


def test_valid_construction_is_local() -> None:
    adapter = _adapter()
    assert adapter.identity.provider == "ollama"
    assert adapter.capabilities.is_local is True


def test_non_ollama_provider_rejected() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        OllamaAdapter(_endpoint(provider="openai"))


def test_missing_base_url_rejected_before_client() -> None:
    client = FakeLiteLLMClient()
    with pytest.raises(AdapterInvalidRequestError):
        OllamaAdapter(_endpoint(base_url=None), client=client)
    assert client.payloads == []


def test_nested_model_allowed() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(client=client, endpoint=_endpoint(model="hf.co/org/example-model"))
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["model"] == "ollama/hf.co/org/example-model"


def test_same_provider_prefixed_model_rejected() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        OllamaAdapter(_endpoint(model="ollama/example-model"))


def test_constructed_without_any_secret_provider() -> None:
    # OllamaAdapter takes no SecretProvider; local Ollama needs no credential.
    adapter = OllamaAdapter(_endpoint(), client=FakeLiteLLMClient())
    assert adapter.identity.provider == "ollama"


# --- payload ------------------------------------------------------------------


def test_base_url_passed_verbatim_no_path_appended() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert client.payloads[0]["api_base"] == _BASE


def test_no_api_key_in_payload() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert "api_key" not in client.payloads[0]


def test_stream_disabled_and_no_retries() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert client.payloads[0]["stream"] is False
    assert client.payloads[0]["num_retries"] == 0


def test_model_id_composed_once() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert client.payloads[0]["model"] == "ollama/example-model"


def test_request_timeout_overrides_endpoint() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(client=client, endpoint=_endpoint(timeout_seconds=60.0))
    asyncio.run(adapter.complete(_request(timeout=30.5)))
    assert client.payloads[0]["timeout"] == 30.5


def test_endpoint_timeout_used_when_request_absent() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(client=client, endpoint=_endpoint(timeout_seconds=45.0))
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["timeout"] == 45.0


def test_default_timeout_when_both_absent() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert client.payloads[0]["timeout"] == 120.0


def test_messages_mapped_and_request_not_mutated() -> None:
    client = FakeLiteLLMClient()
    request = _request()
    snapshot = _request()
    asyncio.run(_adapter(client=client).complete(request))
    assert client.payloads[0]["messages"] == [
        {"role": "system", "content": "DO-NOT-LOG-PROMPT"},
        {"role": "user", "content": "hi"},
    ]
    assert request == snapshot


# --- response / usage ---------------------------------------------------------


def test_successful_response_normalized() -> None:
    client = FakeLiteLLMClient(responses=[make_raw_response(content="answer")])
    response = asyncio.run(_adapter(client=client).complete(_request()))
    assert response.text == "answer"
    assert response.provider == "ollama"
    assert response.model == "example-model"
    assert response.usage.status is UsageStatus.MEASURED


def test_missing_usage_is_unavailable() -> None:
    client = FakeLiteLLMClient(responses=[make_raw_response(usage=None)])
    response = asyncio.run(_adapter(client=client).complete(_request()))
    assert response.usage.status is UsageStatus.UNAVAILABLE


def test_malformed_response_raises() -> None:
    client = FakeLiteLLMClient(responses=[make_raw_response(choices=[])])
    with pytest.raises(AdapterResponseError):
        asyncio.run(_adapter(client=client).complete(_request()))


# --- errors -------------------------------------------------------------------


def test_connection_refused_maps_to_connection_error() -> None:
    exc = litellm.APIConnectionError(message="connection refused", llm_provider="ollama", model="m")
    client = FakeLiteLLMClient(error=exc)
    with pytest.raises(AdapterConnectionError) as info:
        asyncio.run(_adapter(client=client).complete(_request()))
    assert info.value.retryable is True


def test_timeout_maps_to_timeout_error() -> None:
    exc = litellm.Timeout(message="timed out", model="m", llm_provider="ollama")
    client = FakeLiteLLMClient(error=exc)
    with pytest.raises(AdapterTimeoutError) as info:
        asyncio.run(_adapter(client=client).complete(_request()))
    assert info.value.retryable is True


def test_cancellation_propagates_unwrapped() -> None:
    client = FakeLiteLLMClient(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_adapter(client=client).complete(_request()))


# --- logging ------------------------------------------------------------------


def test_logs_are_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    asyncio.run(_adapter().complete(_request()))
    text = caplog.text
    assert "ollama" in text and "example-model" in text
    assert "DO-NOT-LOG-PROMPT" not in text
    assert _BASE not in text
