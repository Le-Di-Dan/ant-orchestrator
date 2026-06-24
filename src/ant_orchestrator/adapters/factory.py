"""Production LLM adapter factory (CP6).

Maps a :class:`ModelEndpointConfig` to a concrete :class:`LLMAdapter` using
explicit, auditable branching over the two providers supported in Phase 2. There
is deliberately no plugin registry, dynamic import, DI container, fallback,
router or cache: with only ``openai`` and ``ollama``, explicit branching is the
clearest and safest design.

The factory only *constructs* adapters — it performs no network call, no secret
lookup and no provider ping. The provider string is matched verbatim (no
strip/lowercase); an unsupported provider (including the test-only ``fake``) is
rejected with a structured :class:`ConfigInvalid` before any client is touched,
so no ``KeyError``/raw ``ValueError``/SDK/import error can leak.
"""

from __future__ import annotations

from ant_orchestrator.adapters.litellm_client import LiteLLMCompletionClient
from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
from ant_orchestrator.adapters.ollama_local import OllamaAdapter
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.application.ports.secrets import SecretProvider
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.models import ModelEndpointConfig

_OPENAI = "openai"
_OLLAMA = "ollama"


def build_llm_adapter(
    endpoint: ModelEndpointConfig,
    *,
    secret_provider: SecretProvider,
    completion_client: LiteLLMCompletionClient,
) -> LLMAdapter:
    """Build the concrete adapter for ``endpoint`` (construction only, no network).

    ``secret_provider`` is wired into the cloud adapter (the secret is read only
    at invocation time, not here). ``completion_client`` is the shared LiteLLM
    seam injected into whichever adapter is built. An unsupported provider raises
    :class:`ConfigInvalid`.
    """
    provider = endpoint.provider
    if provider == _OPENAI:
        return LiteLLMCloudAdapter(endpoint, secret_provider, client=completion_client)
    if provider == _OLLAMA:
        return OllamaAdapter(endpoint, client=completion_client)
    raise ConfigInvalid(f"unsupported model provider: {provider!r}")
