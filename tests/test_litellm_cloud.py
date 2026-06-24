"""Behavioural tests for LiteLLMCloudAdapter (CP3; fake seam, no network)."""

from __future__ import annotations

import asyncio
import logging

import pytest

from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
from ant_orchestrator.application.ports.llm import (
    LLMMessage,
    LLMRequest,
    MessageRole,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterInvalidRequestError,
    AdapterResponseError,
)
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.support.fake_litellm import FakeLiteLLMClient, make_raw_response
from tests.support.fake_secret_provider import FakeSecretProvider

_SECRET = "sk-secret-deadbeef"
_LOGGER = "ant_orchestrator.adapters.llm"


def _endpoint(
    *,
    model: str = "example-model",
    timeout_seconds: float | None = None,
    base_url: str | None = None,
) -> ModelEndpointConfig:
    return ModelEndpointConfig(
        provider="openai", model=model, timeout_seconds=timeout_seconds, base_url=base_url
    )


def _adapter(
    *,
    secret: str | None = _SECRET,
    client: FakeLiteLLMClient | None = None,
    endpoint: ModelEndpointConfig | None = None,
) -> LiteLLMCloudAdapter:
    secrets = FakeSecretProvider({"OPENAI_API_KEY": secret} if secret is not None else {})
    return LiteLLMCloudAdapter(
        endpoint or _endpoint(), secrets, client=client or FakeLiteLLMClient()
    )


def _request(*, timeout: float | None = None) -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "hi"),),
        system_prompt="DO-NOT-LOG-PROMPT",
        timeout_seconds=timeout,
    )


# --- construction / config ----------------------------------------------------


def test_valid_construction() -> None:
    adapter = _adapter()
    assert adapter.identity.provider == "openai"
    assert adapter.capabilities.is_local is False


def test_unsupported_provider_rejected() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        LiteLLMCloudAdapter(
            ModelEndpointConfig(provider="anthropic", model="m"), FakeSecretProvider()
        )


def test_prefixed_model_rejected_at_construction() -> None:
    with pytest.raises(AdapterInvalidRequestError):
        _adapter(endpoint=_endpoint(model="openai/example-model"))


# --- secret -------------------------------------------------------------------


def test_missing_secret_raises_auth_without_calling_sdk() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(secret=None, client=client)
    with pytest.raises(AdapterAuthenticationError) as info:
        asyncio.run(adapter.complete(_request()))
    assert info.value.retryable is False
    assert client.payloads == []


def test_present_secret_passed_verbatim() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(secret="  spaced-secret  ", client=client)
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["api_key"] == "  spaced-secret  "


def test_auth_error_does_not_leak_secret() -> None:
    adapter = _adapter(secret=None)
    with pytest.raises(AdapterAuthenticationError) as info:
        asyncio.run(adapter.complete(_request()))
    assert "OPENAI_API_KEY" not in str(info.value)


# --- timeout / payload --------------------------------------------------------


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
    adapter = _adapter(client=client)
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["timeout"] == 120.0


def test_stream_disabled_and_no_retries() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(client=client)
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["stream"] is False
    assert client.payloads[0]["num_retries"] == 0


def test_model_id_composed_once_in_payload() -> None:
    client = FakeLiteLLMClient()
    adapter = _adapter(client=client)
    asyncio.run(adapter.complete(_request()))
    assert client.payloads[0]["model"] == "openai/example-model"


def test_base_url_passed_only_when_present() -> None:
    client = FakeLiteLLMClient()
    asyncio.run(_adapter(client=client).complete(_request()))
    assert "api_base" not in client.payloads[0]
    client2 = FakeLiteLLMClient()
    adapter = _adapter(client=client2, endpoint=_endpoint(base_url="http://local"))
    asyncio.run(adapter.complete(_request()))
    assert client2.payloads[0]["api_base"] == "http://local"


def test_request_not_mutated() -> None:
    request = _request()
    snapshot = _request()
    asyncio.run(_adapter().complete(request))
    assert request == snapshot


# --- response / errors --------------------------------------------------------


def test_successful_response_normalized() -> None:
    client = FakeLiteLLMClient(responses=[make_raw_response(content="answer")])
    response = asyncio.run(_adapter(client=client).complete(_request()))
    assert response.text == "answer"
    assert response.provider == "openai"
    assert response.model == "example-model"
    assert response.usage.status is UsageStatus.MEASURED


def test_malformed_response_raises_response_error() -> None:
    client = FakeLiteLLMClient(responses=[make_raw_response(choices=[])])
    with pytest.raises(AdapterResponseError):
        asyncio.run(_adapter(client=client).complete(_request()))


def test_cancellation_propagates_unwrapped() -> None:
    client = FakeLiteLLMClient(error=asyncio.CancelledError())
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_adapter(client=client).complete(_request()))


# --- sanitized logging --------------------------------------------------------


def test_success_log_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    adapter = _adapter(endpoint=_endpoint(base_url="http://secret-base"))
    asyncio.run(adapter.complete(_request()))
    text = caplog.text
    assert "openai" in text and "example-model" in text
    assert "measured" in text
    assert "DO-NOT-LOG-PROMPT" not in text
    assert _SECRET not in text
    assert "http://secret-base" not in text


def test_failure_log_is_sanitized(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger=_LOGGER)
    client = FakeLiteLLMClient(responses=[make_raw_response(choices=[])])
    with pytest.raises(AdapterResponseError):
        asyncio.run(_adapter(client=client).complete(_request()))
    assert "llm.complete.failure" in caplog.text
    assert "adapter.response" in caplog.text
    assert "DO-NOT-LOG-PROMPT" not in caplog.text
