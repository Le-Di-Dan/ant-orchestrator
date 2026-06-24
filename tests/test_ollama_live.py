"""Gated live Ollama smoke test (CP4 artifact; skipped by default).

Runs a real local Ollama call through the public LLMAdapter contract only when
both ``ANT_LIVE_OLLAMA_MODEL`` and ``ANT_LIVE_OLLAMA_BASE_URL`` are set, so no model
or endpoint is hard-coded and the automated gate never touches a local service.
The mandatory live verification + sanitized evidence happens at CP6.
"""

from __future__ import annotations

import asyncio
import os

import pytest

pytestmark = pytest.mark.live_ollama

_HAVE_CONFIG = bool(
    os.environ.get("ANT_LIVE_OLLAMA_MODEL") and os.environ.get("ANT_LIVE_OLLAMA_BASE_URL")
)


@pytest.mark.skipif(
    not _HAVE_CONFIG,
    reason="set ANT_LIVE_OLLAMA_MODEL and ANT_LIVE_OLLAMA_BASE_URL to run the live Ollama test",
)
def test_live_ollama_smoke() -> None:
    from ant_orchestrator.adapters.ollama_local import OllamaAdapter
    from ant_orchestrator.application.ports.llm import (
        FinishReason,
        LLMMessage,
        LLMRequest,
        MessageRole,
        UsageStatus,
    )
    from ant_orchestrator.config.models import ModelEndpointConfig

    model = os.environ["ANT_LIVE_OLLAMA_MODEL"]
    adapter = OllamaAdapter(
        ModelEndpointConfig(
            provider="ollama",
            model=model,
            base_url=os.environ["ANT_LIVE_OLLAMA_BASE_URL"],
        )
    )
    request = LLMRequest(
        messages=(LLMMessage(MessageRole.USER, "Reply with the single word OK."),),
        max_output_tokens=5,
        timeout_seconds=30.0,
    )
    response = asyncio.run(adapter.complete(request))
    assert response.provider == "ollama"
    assert response.model == model
    assert adapter.capabilities.is_local is True
    assert isinstance(response.text, str) and response.text  # never log content
    assert isinstance(response.finish_reason, FinishReason)
    assert response.usage.status in (UsageStatus.MEASURED, UsageStatus.UNAVAILABLE)
