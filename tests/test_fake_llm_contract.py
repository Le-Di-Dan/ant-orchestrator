"""FakeLLMAdapter conformance to the reusable LLM contract + fake-specific tests."""

from __future__ import annotations

import asyncio

from ant_orchestrator.application.ports.llm import (
    LLMAdapter,
    LLMResponse,
    ModelUsage,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import AdapterError
from tests.contracts.llm_contract import LLMAdapterContract, make_request
from tests.support.fake_llm import FakeLLMAdapter, fake_with_error


class TestFakeLLMAdapterContract(LLMAdapterContract):
    """Run the shared LLM contract against FakeLLMAdapter."""

    def build_success_adapter(self) -> LLMAdapter:
        return FakeLLMAdapter()

    def build_unavailable_usage_adapter(self) -> LLMAdapter:
        response = LLMResponse(
            text="x", provider="fake", model="fake-model", usage=ModelUsage.unavailable()
        )
        return FakeLLMAdapter(responses=[response])

    def build_error_adapter(self, error: AdapterError) -> LLMAdapter:
        return fake_with_error(error)


def test_fake_records_received_requests() -> None:
    adapter = FakeLLMAdapter()
    request = make_request()
    asyncio.run(adapter.complete(request))
    assert adapter.received == [request]


def test_fake_default_response_has_measured_usage() -> None:
    adapter = FakeLLMAdapter()
    response = asyncio.run(adapter.complete(make_request()))
    assert response.usage.status is UsageStatus.MEASURED
    assert response.provider == "fake"


def test_fake_returns_scripted_responses_in_order() -> None:
    first = LLMResponse(text="one", provider="fake", model="m", usage=ModelUsage.measured(1, 1))
    second = LLMResponse(text="two", provider="fake", model="m", usage=ModelUsage.unavailable())
    adapter = FakeLLMAdapter(responses=[first, second])
    assert asyncio.run(adapter.complete(make_request())).text == "one"
    assert asyncio.run(adapter.complete(make_request())).text == "two"
