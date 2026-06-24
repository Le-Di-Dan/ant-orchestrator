"""Production LLM adapter factory tests (CP6).

All deterministic and offline: a fake completion client and a tracking secret
provider prove that construction performs no network call and no secret lookup.
"""

from __future__ import annotations

import pytest

from ant_orchestrator.adapters.factory import build_llm_adapter
from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
from ant_orchestrator.adapters.ollama_local import OllamaAdapter
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.support.fake_litellm import FakeLiteLLMClient

_OPENAI = ModelEndpointConfig(provider="openai", model="gpt-4o-mini")
_OLLAMA = ModelEndpointConfig(
    provider="ollama", model="qwen2.5-coder", base_url="http://localhost:11434"
)


class _TrackingSecretProvider:
    """SecretProvider that records every lookup so construction can be audited."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    def get(self, name: str) -> str | None:
        self.lookups.append(name)
        return "unused-secret"


def _build(
    endpoint: ModelEndpointConfig,
) -> tuple[LLMAdapter, _TrackingSecretProvider, FakeLiteLLMClient]:
    secrets = _TrackingSecretProvider()
    client = FakeLiteLLMClient()
    adapter = build_llm_adapter(endpoint, secret_provider=secrets, completion_client=client)
    return adapter, secrets, client


def test_openai_endpoint_builds_cloud_adapter() -> None:
    adapter, _, _ = _build(_OPENAI)
    assert isinstance(adapter, LiteLLMCloudAdapter)


def test_ollama_endpoint_builds_local_adapter() -> None:
    adapter, _, _ = _build(_OLLAMA)
    assert isinstance(adapter, OllamaAdapter)


def test_unsupported_provider_rejected_before_client_call() -> None:
    secrets = _TrackingSecretProvider()
    client = FakeLiteLLMClient()
    with pytest.raises(ConfigInvalid):
        build_llm_adapter(
            ModelEndpointConfig(provider="anthropic", model="claude"),
            secret_provider=secrets,
            completion_client=client,
        )
    assert client.payloads == []
    assert secrets.lookups == []


def test_fake_provider_is_rejected() -> None:
    secrets = _TrackingSecretProvider()
    client = FakeLiteLLMClient()
    with pytest.raises(ConfigInvalid):
        build_llm_adapter(
            ModelEndpointConfig(provider="fake", model="x"),
            secret_provider=secrets,
            completion_client=client,
        )


@pytest.mark.parametrize("provider", [" openai", "openai ", "OpenAI", " ollama"])
def test_provider_is_matched_verbatim_without_autocorrect(provider: str) -> None:
    # The factory never strips/lowercases; a non-canonical provider is unsupported.
    with pytest.raises(ConfigInvalid):
        build_llm_adapter(
            ModelEndpointConfig(provider=provider, model="x", base_url="http://x"),
            secret_provider=_TrackingSecretProvider(),
            completion_client=FakeLiteLLMClient(),
        )


def test_openai_construction_does_not_lookup_secret() -> None:
    _, secrets, _ = _build(_OPENAI)
    assert secrets.lookups == []


def test_openai_construction_does_not_call_completion_client() -> None:
    _, _, client = _build(_OPENAI)
    assert client.payloads == []


def test_ollama_construction_does_not_call_completion_client() -> None:
    _, _, client = _build(_OLLAMA)
    assert client.payloads == []


def test_ollama_missing_base_url_rejected() -> None:
    with pytest.raises(Exception) as info:
        build_llm_adapter(
            ModelEndpointConfig(provider="ollama", model="qwen2.5-coder"),
            secret_provider=_TrackingSecretProvider(),
            completion_client=FakeLiteLLMClient(),
        )
    # The Ollama adapter rejects a missing base_url at construction time.
    assert info.type is not ConfigInvalid


def test_adapter_identity_provider_matches_endpoint() -> None:
    cloud, _, _ = _build(_OPENAI)
    local, _, _ = _build(_OLLAMA)
    assert cloud.identity.provider == "openai"
    assert local.identity.provider == "ollama"


def test_cloud_is_not_local() -> None:
    cloud, _, _ = _build(_OPENAI)
    assert cloud.capabilities.is_local is False


def test_ollama_is_local() -> None:
    local, _, _ = _build(_OLLAMA)
    assert local.capabilities.is_local is True
