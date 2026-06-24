"""Unit tests for the LLM adapter DTOs, usage semantics and error taxonomy (CP1)."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from ant_orchestrator.application.ports.llm import (
    AdapterCapabilities,
    AdapterIdentity,
    LLMRequest,
    LLMResponse,
    ModelUsage,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterConnectionError,
    AdapterError,
    AdapterErrorCode,
    AdapterInvalidRequestError,
    AdapterProviderError,
    AdapterRateLimitError,
    AdapterResponseError,
    AdapterTimeoutError,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount
from ant_orchestrator.errors import AntError

# --- ModelUsage / UsageStatus -------------------------------------------------


def test_measured_usage_is_valid_and_consistent() -> None:
    usage = ModelUsage.measured(tokens_in=10, tokens_out=5)
    assert usage.status is UsageStatus.MEASURED
    assert usage.tokens_in == TokenCount(10)
    assert usage.tokens_out == TokenCount(5)
    assert usage.tokens_total == TokenCount(15)


def test_unavailable_usage_carries_no_tokens() -> None:
    usage = ModelUsage.unavailable()
    assert usage.status is UsageStatus.UNAVAILABLE
    assert usage.tokens_in is None
    assert usage.tokens_out is None
    assert usage.tokens_total is None


def test_unavailable_usage_with_tokens_is_rejected() -> None:
    with pytest.raises(InvariantViolation):
        ModelUsage(UsageStatus.UNAVAILABLE, tokens_in=TokenCount(1))


def test_measured_usage_requires_both_in_and_out() -> None:
    with pytest.raises(InvariantViolation):
        ModelUsage(UsageStatus.MEASURED, tokens_in=TokenCount(1))


def test_negative_token_count_is_rejected() -> None:
    with pytest.raises(InvariantViolation):
        TokenCount(-1)


def test_inconsistent_total_is_rejected() -> None:
    with pytest.raises(InvariantViolation):
        ModelUsage(
            UsageStatus.MEASURED,
            tokens_in=TokenCount(2),
            tokens_out=TokenCount(3),
            tokens_total=TokenCount(99),
        )


def test_estimated_usage_follows_same_shape_rules() -> None:
    usage = ModelUsage(
        UsageStatus.ESTIMATED,
        tokens_in=TokenCount(4),
        tokens_out=TokenCount(6),
        tokens_total=TokenCount(10),
    )
    assert usage.status is UsageStatus.ESTIMATED


# --- DTO immutability / invariants -------------------------------------------


def test_request_has_no_model_field() -> None:
    # A request carries content/options only; provider/model is endpoint-scoped.
    from dataclasses import fields

    assert "model" not in {f.name for f in fields(LLMRequest)}


def test_response_is_frozen() -> None:
    response = LLMResponse(text="hi", provider="p", model="m", usage=ModelUsage.unavailable())
    with pytest.raises(FrozenInstanceError):
        response.text = "mutated"  # type: ignore[misc]


def test_response_requires_provider_and_model() -> None:
    with pytest.raises(InvariantViolation):
        LLMResponse(text="x", provider="", model="m", usage=ModelUsage.unavailable())
    with pytest.raises(InvariantViolation):
        LLMResponse(text="x", provider="p", model="", usage=ModelUsage.unavailable())


def test_identity_rejects_empty_provider() -> None:
    with pytest.raises(InvariantViolation):
        AdapterIdentity(provider="")


def test_capabilities_default_is_not_local_cost_free() -> None:
    caps = AdapterCapabilities(is_local=False)
    assert caps.supports_system_prompt is True
    assert caps.max_context_tokens is None
    assert not hasattr(caps, "cost")


# --- Error taxonomy ----------------------------------------------------------

_EXPECTED = [
    (AdapterTimeoutError, AdapterErrorCode.TIMEOUT, True),
    (AdapterConnectionError, AdapterErrorCode.CONNECTION, True),
    (AdapterRateLimitError, AdapterErrorCode.RATE_LIMIT, True),
    (AdapterAuthenticationError, AdapterErrorCode.AUTHENTICATION, False),
    (AdapterInvalidRequestError, AdapterErrorCode.INVALID_REQUEST, False),
    (AdapterProviderError, AdapterErrorCode.PROVIDER, False),
    (AdapterResponseError, AdapterErrorCode.RESPONSE, False),
]


@pytest.mark.parametrize(("error_cls", "code", "retryable"), _EXPECTED)
def test_error_code_and_default_retryable(
    error_cls: type[AdapterError], code: AdapterErrorCode, retryable: bool
) -> None:
    error = error_cls("boom")
    assert isinstance(error, AntError)
    assert error.code is code
    assert error.retryable is retryable


def test_authentication_is_not_an_invalid_request() -> None:
    assert not issubclass(AdapterAuthenticationError, AdapterInvalidRequestError)
    assert not issubclass(AdapterInvalidRequestError, AdapterAuthenticationError)


def test_provider_error_retryable_can_be_overridden() -> None:
    assert AdapterProviderError("x", retryable=True).retryable is True


def test_error_repr_excludes_message_payload() -> None:
    error = AdapterProviderError("boom containing SECRET-XYZ", provider="prov", model="mod")
    rendered = repr(error)
    assert "SECRET-XYZ" not in rendered
    assert "adapter.provider" in rendered
    assert "prov" in rendered
    assert "mod" in rendered
