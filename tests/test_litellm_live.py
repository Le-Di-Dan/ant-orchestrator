"""Gated live OpenAI smoke test (CP3 artifact; skipped by default).

Runs a real OpenAI call through the public LLMAdapter contract only when both
``OPENAI_API_KEY`` and ``ANT_LIVE_OPENAI_MODEL`` are set in the environment, so no
model id is hard-coded and the automated gate never touches the network. The
mandatory successful live verification + sanitized evidence happens at CP6.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.live_openai

_HAVE_CREDS = bool(os.environ.get("OPENAI_API_KEY") and os.environ.get("ANT_LIVE_OPENAI_MODEL"))


@pytest.mark.skipif(
    not _HAVE_CREDS,
    reason="set OPENAI_API_KEY and ANT_LIVE_OPENAI_MODEL to run the live OpenAI smoke test",
)
def test_live_openai_smoke() -> None:
    from ant_orchestrator.adapters.env_secret_provider import EnvSecretProvider
    from ant_orchestrator.adapters.litellm_cloud import LiteLLMCloudAdapter
    from ant_orchestrator.application.ports.llm import (
        FinishReason,
        LLMMessage,
        LLMRequest,
        MessageRole,
        UsageStatus,
    )
    from ant_orchestrator.config.models import ModelEndpointConfig

    model = os.environ["ANT_LIVE_OPENAI_MODEL"]
    adapter = LiteLLMCloudAdapter(
        ModelEndpointConfig(provider="openai", model=model), EnvSecretProvider()
    )
    request = LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "Reply with the single word OK."),),
        max_output_tokens=5,
        timeout_seconds=30.0,
    )
    response = asyncio.run(adapter.complete(request))
    assert response.provider == "openai"
    assert response.model == model
    assert adapter.capabilities.is_local is False
    assert isinstance(response.text, str) and response.text  # never log content
    assert isinstance(response.finish_reason, FinishReason)
    assert response.usage.status in (UsageStatus.MEASURED, UsageStatus.UNAVAILABLE)
