"""Unit tests for the LiteLLM mapping layer (CP3; no LiteLLM import needed)."""

from __future__ import annotations

import pytest

from ant_orchestrator.adapters.litellm_mapping import (
    build_litellm_model_id,
    normalize_response,
    to_completion_payload,
)
from ant_orchestrator.application.ports.llm import (
    FinishReason,
    LLMMessage,
    LLMRequest,
    MessageRole,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterInvalidRequestError,
    AdapterResponseError,
)
from tests.support.fake_litellm import make_raw_response, make_usage

# --- model id -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider", "model", "expected"),
    [
        ("openai", "example-model", "openai/example-model"),
        ("openrouter", "anthropic/example-model", "openrouter/anthropic/example-model"),
        ("huggingface", "org/example-model", "huggingface/org/example-model"),
        ("ollama", "hf.co/org/example-model", "ollama/hf.co/org/example-model"),
        # A nested segment that is NOT this provider's prefix is allowed.
        ("openrouter", "openai/example-model", "openrouter/openai/example-model"),
    ],
)
def test_model_id_composed_once(provider: str, model: str, expected: str) -> None:
    assert build_litellm_model_id(provider, model) == expected


@pytest.mark.parametrize(
    ("provider", "model"),
    [("openai", "openai/example-model"), ("ollama", "ollama/example-model")],
)
def test_same_provider_prefix_rejected(provider: str, model: str) -> None:
    with pytest.raises(AdapterInvalidRequestError):
        build_litellm_model_id(provider, model)


# --- request payload ----------------------------------------------------------


def _request() -> LLMRequest:
    return LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "hi"),),
        system_prompt="be brief",
        temperature=0.2,
        max_output_tokens=100,
    )


def test_payload_is_explicit_and_safe() -> None:
    payload = to_completion_payload(
        _request(), model_id="openai/m", api_key="sk-1", base_url=None, timeout=42.0
    )
    assert payload["model"] == "openai/m"
    assert payload["api_key"] == "sk-1"
    assert payload["timeout"] == 42.0
    assert payload["stream"] is False
    assert payload["num_retries"] == 0
    assert payload["temperature"] == 0.2
    assert payload["max_tokens"] == 100
    assert "api_base" not in payload


def test_payload_messages_map_roles_and_prepend_system() -> None:
    payload = to_completion_payload(
        _request(), model_id="openai/m", api_key="k", base_url=None, timeout=1.0
    )
    assert payload["messages"] == [
        {"role": "system", "content": "be brief"},
        {"role": "user", "content": "hi"},
    ]


def test_payload_includes_base_url_when_present() -> None:
    payload = to_completion_payload(
        _request(), model_id="openai/m", api_key="k", base_url="http://x", timeout=1.0
    )
    assert payload["api_base"] == "http://x"


def test_payload_does_not_mutate_request() -> None:
    request = _request()
    snapshot = _request()
    to_completion_payload(request, model_id="openai/m", api_key="k", base_url=None, timeout=1.0)
    assert request == snapshot


def test_payload_omits_optional_fields_when_absent() -> None:
    request = LLMRequest(messages=(LLMMessage(MessageRole.USER, "hi"),))
    payload = to_completion_payload(
        request, model_id="openai/m", api_key="k", base_url=None, timeout=1.0
    )
    assert "temperature" not in payload
    assert "max_tokens" not in payload
    assert payload["messages"] == [{"role": "user", "content": "hi"}]


# --- response content / finish reason -----------------------------------------


def test_normalize_valid_content() -> None:
    resp = normalize_response(make_raw_response(content="answer"), provider="openai", model="m")
    assert resp.text == "answer"
    assert resp.provider == "openai"
    assert resp.model == "m"


def test_missing_choices_raises() -> None:
    with pytest.raises(AdapterResponseError):
        normalize_response(make_raw_response(choices=[]), provider="openai", model="m")


def test_non_string_content_raises() -> None:
    with pytest.raises(AdapterResponseError):
        normalize_response(make_raw_response(content=None), provider="openai", model="m")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("stop", FinishReason.STOP),
        ("length", FinishReason.LENGTH),
        ("max_tokens", FinishReason.LENGTH),
        ("content_filter", FinishReason.CONTENT_FILTER),
        ("tool_calls", FinishReason.UNKNOWN),
        (None, FinishReason.UNKNOWN),
    ],
)
def test_finish_reason_mapping(raw: object, expected: FinishReason) -> None:
    resp = normalize_response(make_raw_response(finish_reason=raw), provider="openai", model="m")
    assert resp.finish_reason is expected


# --- usage normalization ------------------------------------------------------


def test_measured_usage() -> None:
    resp = normalize_response(
        make_raw_response(usage=make_usage(10, 20, 30)), provider="openai", model="m"
    )
    assert resp.usage.status is UsageStatus.MEASURED
    assert resp.usage.tokens_in is not None and resp.usage.tokens_in.value == 10
    assert resp.usage.tokens_total is not None and resp.usage.tokens_total.value == 30


def test_measured_usage_total_computed_when_absent() -> None:
    resp = normalize_response(
        make_raw_response(usage=make_usage(10, 20, None)), provider="openai", model="m"
    )
    assert resp.usage.status is UsageStatus.MEASURED
    assert resp.usage.tokens_total is not None and resp.usage.tokens_total.value == 30


def test_missing_usage_is_unavailable() -> None:
    resp = normalize_response(make_raw_response(usage=None), provider="openai", model="m")
    assert resp.usage.status is UsageStatus.UNAVAILABLE
    assert resp.usage.tokens_in is None


def test_partial_usage_is_unavailable_not_zeroed() -> None:
    resp = normalize_response(
        make_raw_response(usage=make_usage(10, None, None)), provider="openai", model="m"
    )
    assert resp.usage.status is UsageStatus.UNAVAILABLE
    assert resp.usage.tokens_in is None


def test_inconsistent_total_raises() -> None:
    with pytest.raises(AdapterResponseError):
        normalize_response(
            make_raw_response(usage=make_usage(10, 20, 999)), provider="openai", model="m"
        )


@pytest.mark.parametrize("bad", [-1, True, 10.5])
def test_invalid_token_value_raises(bad: object) -> None:
    with pytest.raises(AdapterResponseError):
        normalize_response(
            make_raw_response(usage=make_usage(bad, 20, None)), provider="openai", model="m"
        )
