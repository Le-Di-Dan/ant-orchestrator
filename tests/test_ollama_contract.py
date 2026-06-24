"""Run the reusable LLM contract against OllamaAdapter (CP4; fake seam)."""

from __future__ import annotations

from ant_orchestrator.adapters.ollama_local import OllamaAdapter
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.application.ports.llm_errors import AdapterError
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.contracts.llm_contract import LLMAdapterContract
from tests.support.fake_litellm import FakeLiteLLMClient, make_raw_response


def _adapter(client: FakeLiteLLMClient) -> OllamaAdapter:
    return OllamaAdapter(
        ModelEndpointConfig(
            provider="ollama", model="example-model", base_url="http://localhost:11434"
        ),
        client=client,
    )


class TestOllamaContract(LLMAdapterContract):
    """OllamaAdapter must satisfy the same contract as every adapter."""

    def build_success_adapter(self) -> LLMAdapter:
        return _adapter(FakeLiteLLMClient(responses=[make_raw_response()]))

    def build_unavailable_usage_adapter(self) -> LLMAdapter:
        return _adapter(FakeLiteLLMClient(responses=[make_raw_response(usage=None)]))

    def build_error_adapter(self, error: AdapterError) -> LLMAdapter:
        return _adapter(FakeLiteLLMClient(error=error))
