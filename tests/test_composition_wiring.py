"""Composition-root wiring tests for the configured LLM adapters (CP6).

Construction must stay fully offline: the production ``EnvSecretProvider`` and
``LiteLLMSdkClient`` perform no work until an actual completion runs, so these
tests need neither network, secret nor a running Ollama.
"""

from __future__ import annotations

from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
from ant_orchestrator.adapters.ollama_local import OllamaAdapter
from ant_orchestrator.cli.composition import (
    ConfiguredLLMAdapters,
    build_configured_llm_adapters,
    build_services,
)
from ant_orchestrator.config.models import (
    ModelEndpointConfig,
    ModelsConfig,
    ProjectConfig,
    ResolvedConfig,
)

_QUEEN = ModelEndpointConfig(provider="openai", model="gpt-4o-mini")
_LOCAL = ModelEndpointConfig(
    provider="ollama", model="qwen2.5-coder", base_url="http://localhost:11434"
)


def _config(models: ModelsConfig) -> ResolvedConfig:
    return ResolvedConfig(version=1, project=ProjectConfig(name="demo"), models=models)


def test_phase1_config_without_models_builds_no_adapters() -> None:
    # ResolvedConfig defaults to an empty ModelsConfig (Phase 1 backward compat).
    result = build_configured_llm_adapters(_config(ModelsConfig()))
    assert result == ConfiguredLLMAdapters(queen=None, local=None)


def test_empty_models_yields_no_adapter_and_no_error() -> None:
    result = build_configured_llm_adapters(
        ResolvedConfig(version=1, project=ProjectConfig(name="demo"))
    )
    assert result.queen is None and result.local is None


def test_queen_only_builds_only_queen() -> None:
    result = build_configured_llm_adapters(_config(ModelsConfig(queen=_QUEEN)))
    assert isinstance(result.queen, LiteLLMCloudAdapter)
    assert result.local is None


def test_local_only_builds_only_local() -> None:
    result = build_configured_llm_adapters(_config(ModelsConfig(local=_LOCAL)))
    assert isinstance(result.local, OllamaAdapter)
    assert result.queen is None


def test_both_endpoints_build_both_adapters() -> None:
    result = build_configured_llm_adapters(_config(ModelsConfig(queen=_QUEEN, local=_LOCAL)))
    assert isinstance(result.queen, LiteLLMCloudAdapter)
    assert isinstance(result.local, OllamaAdapter)


def test_role_is_not_pinned_to_provider() -> None:
    # The factory derives the adapter from each endpoint's provider, so a "queen"
    # slot configured with an ollama endpoint yields an OllamaAdapter.
    result = build_configured_llm_adapters(_config(ModelsConfig(queen=_LOCAL, local=_QUEEN)))
    assert isinstance(result.queen, OllamaAdapter)
    assert isinstance(result.local, LiteLLMCloudAdapter)


def test_build_services_still_succeeds() -> None:
    # The existing Phase 1 composition path is unaffected by the new wiring.
    services = build_services()
    assert services.init_nest is not None
    assert services.nest_status is not None
    assert services.show_config is not None
