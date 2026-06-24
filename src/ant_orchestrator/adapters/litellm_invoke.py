"""Provider-neutral LiteLLM invocation flow shared by cloud & local adapters (CP4).

Runs a pre-built payload through the seam, normalizes the response, maps foreign
exceptions to the neutral taxonomy, logs sanitized metadata, and lets
``asyncio.CancelledError`` propagate unwrapped. Adapters differ only in how they
build the payload (credentials, base URL); the execution path is identical, so it
lives here instead of being duplicated per adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from time import perf_counter

from ant_orchestrator.adapters.adapter_log import log_failure, log_success
from ant_orchestrator.adapters.litellm_client import LiteLLMCompletionClient
from ant_orchestrator.adapters.litellm_errors import map_litellm_error
from ant_orchestrator.adapters.litellm_mapping import normalize_response
from ant_orchestrator.application.ports.llm import LLMResponse
from ant_orchestrator.application.ports.llm_errors import AdapterError


async def run_completion(
    client: LiteLLMCompletionClient,
    payload: Mapping[str, object],
    *,
    provider: str,
    model: str,
) -> LLMResponse:
    """Execute one completion and return a normalized, sanitized-logged response."""
    started = perf_counter()
    try:
        raw = await client.acompletion(payload)
        response = normalize_response(raw, provider=provider, model=model)
    except asyncio.CancelledError:
        raise
    except AdapterError as exc:
        _log_failure(provider, model, started, exc)
        raise
    except Exception as exc:
        error = map_litellm_error(exc, provider=provider, model=model)
        _log_failure(provider, model, started, error)
        raise error from None
    log_success(
        provider=provider,
        model=model,
        duration_ms=_elapsed_ms(started),
        usage=response.usage,
        finish_reason=response.finish_reason.value,
    )
    return response


def _log_failure(provider: str, model: str, started: float, error: AdapterError) -> None:
    log_failure(
        provider=provider,
        model=model,
        duration_ms=_elapsed_ms(started),
        error_code=error.code.value,
        retryable=error.retryable,
    )


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0
