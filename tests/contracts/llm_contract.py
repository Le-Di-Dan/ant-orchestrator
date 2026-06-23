"""Reusable ``LLMAdapter`` contract test kit (CP1).

Subclass :class:`LLMAdapterContract` in a ``Test*`` class and implement the three
builders; the inherited ``test_*`` methods then verify the shared contract. The
base class is intentionally NOT named ``Test*`` so pytest does not collect it
directly (its abstract builders would fail). The same kit is reused by the real
cloud (CP3) and Ollama (CP4) adapters with LiteLLM mocked.
"""

from __future__ import annotations

import asyncio
import inspect

import pytest

from ant_orchestrator.application.ports.llm import (
    LLMAdapter,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    MessageRole,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterAuthenticationError,
    AdapterConnectionError,
    AdapterError,
    AdapterInvalidRequestError,
    AdapterProviderError,
    AdapterRateLimitError,
    AdapterResponseError,
    AdapterTimeoutError,
)

# A marker planted into the request prompt; structured errors must never leak it.
SECRET_MARKER = "SECRET-PROMPT-DO-NOT-LEAK"

# (error class, expected default retryable) — the canonical taxonomy contract.
ERROR_CASES = [
    (AdapterTimeoutError, True),
    (AdapterConnectionError, True),
    (AdapterRateLimitError, True),
    (AdapterAuthenticationError, False),
    (AdapterInvalidRequestError, False),
    (AdapterProviderError, False),
    (AdapterResponseError, False),
]


def make_request(model: str = "contract-model") -> LLMRequest:
    """Build a canonical request carrying a secret-like system prompt."""
    return LLMRequest(
        model=model,
        messages=(LLMMessage(MessageRole.USER, "hello"),),
        system_prompt=SECRET_MARKER,
    )


class LLMAdapterContract:
    """Shared behavioural contract for any :class:`LLMAdapter`."""

    # --- builders implemented by subclasses ------------------------------
    def build_success_adapter(self) -> LLMAdapter:
        raise NotImplementedError

    def build_unavailable_usage_adapter(self) -> LLMAdapter:
        raise NotImplementedError

    def build_error_adapter(self, error: AdapterError) -> LLMAdapter:
        raise NotImplementedError

    # --- contract tests ---------------------------------------------------
    def test_complete_is_a_coroutine_function(self) -> None:
        adapter = self.build_success_adapter()
        assert inspect.iscoroutinefunction(adapter.complete)

    def test_complete_returns_normalized_response(self) -> None:
        adapter = self.build_success_adapter()
        response = asyncio.run(adapter.complete(make_request()))
        assert isinstance(response, LLMResponse)
        assert response.provider
        assert response.model

    def test_measured_usage_is_consistent(self) -> None:
        adapter = self.build_success_adapter()
        usage = asyncio.run(adapter.complete(make_request())).usage
        if usage.status is UsageStatus.MEASURED:
            assert usage.tokens_in is not None
            assert usage.tokens_out is not None
            if usage.tokens_total is not None:
                assert usage.tokens_total.value == usage.tokens_in.value + usage.tokens_out.value

    def test_unavailable_usage_is_not_zeroed(self) -> None:
        adapter = self.build_unavailable_usage_adapter()
        usage = asyncio.run(adapter.complete(make_request())).usage
        assert usage.status is UsageStatus.UNAVAILABLE
        assert usage.tokens_in is None
        assert usage.tokens_out is None
        assert usage.tokens_total is None

    def test_identity_and_capabilities_present(self) -> None:
        adapter = self.build_success_adapter()
        assert adapter.identity.provider
        assert isinstance(adapter.capabilities.is_local, bool)

    def test_request_is_not_mutated(self) -> None:
        adapter = self.build_success_adapter()
        request = make_request()
        snapshot = make_request()
        asyncio.run(adapter.complete(request))
        assert request == snapshot

    @pytest.mark.parametrize(("error_cls", "expected_retryable"), ERROR_CASES)
    def test_error_taxonomy_and_sanitization(
        self, error_cls: type[AdapterError], expected_retryable: bool
    ) -> None:
        error = error_cls("provider failure", provider="prov", model="mod")
        adapter = self.build_error_adapter(error)
        with pytest.raises(error_cls) as exc_info:
            asyncio.run(adapter.complete(make_request()))
        raised = exc_info.value
        assert raised.retryable is expected_retryable
        assert raised.code is error_cls.code
        # The planted secret prompt must never surface in the error.
        assert SECRET_MARKER not in str(raised)
        assert SECRET_MARKER not in repr(raised)
