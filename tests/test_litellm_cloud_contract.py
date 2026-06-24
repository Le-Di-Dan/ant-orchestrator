"""Run the reusable LLM contract against LiteLLMCloudAdapter (CP3; fake seam)."""

from __future__ import annotations

from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.application.ports.llm_errors import AdapterError
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.contracts.llm_contract import LLMAdapterContract
from tests.support.fake_litellm import FakeLiteLLMClient, make_raw_response
from tests.support.fake_secret_provider import FakeSecretProvider


def _adapter(client: FakeLiteLLMClient) -> LiteLLMCloudAdapter:
    return LiteLLMCloudAdapter(
        ModelEndpointConfig(provider="openai", model="example-model"),
        FakeSecretProvider({"OPENAI_API_KEY": "sk-test"}),
        client=client,
    )


class TestLiteLLMCloudContract(LLMAdapterContract):
    """LiteLLMCloudAdapter must satisfy the same contract as every adapter."""

    def build_success_adapter(self) -> LLMAdapter:
        return _adapter(FakeLiteLLMClient(responses=[make_raw_response()]))

    def build_unavailable_usage_adapter(self) -> LLMAdapter:
        return _adapter(FakeLiteLLMClient(responses=[make_raw_response(usage=None)]))

    def build_error_adapter(self, error: AdapterError) -> LLMAdapter:
        # A seam that raises an already-sanitized AdapterError must pass through
        # unchanged (the adapter only maps foreign exceptions).
        return _adapter(FakeLiteLLMClient(error=error))
