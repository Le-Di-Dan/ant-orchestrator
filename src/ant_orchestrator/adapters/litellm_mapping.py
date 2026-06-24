"""Pure mapping between the neutral LLM contract and the LiteLLM SDK (CP3).

No LiteLLM/OpenAI type crosses out of this module: inputs are the neutral
``LLMRequest``/config values, outputs are ``LLMResponse`` and the request payload
(a plain mapping). ``raw`` provider responses are read structurally (duck-typed),
so unit tests can supply lightweight fakes without importing LiteLLM.
"""

from __future__ import annotations

from typing import Any

from ant_orchestrator.application.ports.llm import (
    FinishReason,
    LLMRequest,
    LLMResponse,
    ModelUsage,
    UsageStatus,
)
from ant_orchestrator.application.ports.llm_errors import (
    AdapterInvalidRequestError,
    AdapterResponseError,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount

# LiteLLM finish-reason strings → neutral enum. Unknown values map to UNKNOWN
# (never silently to STOP).
_FINISH_REASONS = {
    "stop": FinishReason.STOP,
    "length": FinishReason.LENGTH,
    "max_tokens": FinishReason.LENGTH,
    "content_filter": FinishReason.CONTENT_FILTER,
}


def build_litellm_model_id(provider: str, model: str) -> str:
    """Compose the ``<provider>/<model>`` id exactly once.

    ``model`` is a provider-native identifier that may itself contain ``/`` for
    nested namespaces (e.g. ``org/name`` on Hugging Face, ``anthropic/name`` on
    OpenRouter). Only a model that already begins with *this provider's* prefix is
    rejected, to avoid a double prefix; the value is never stripped or normalized.
    """
    prefix = f"{provider}/"
    if model.startswith(prefix):
        raise AdapterInvalidRequestError(
            "model id must not repeat the provider prefix", provider=provider, model=model
        )
    return f"{prefix}{model}"


def to_completion_payload(
    request: LLMRequest,
    *,
    model_id: str,
    api_key: str,
    base_url: str | None,
    timeout: float,
) -> dict[str, object]:
    """Build an explicit, allow-listed LiteLLM payload (no request mutation)."""
    messages: list[dict[str, str]] = []
    if request.system_prompt is not None:
        messages.append({"role": "system", "content": request.system_prompt})
    messages.extend({"role": m.role.value, "content": m.content} for m in request.messages)

    payload: dict[str, object] = {
        "model": model_id,
        "messages": messages,
        "api_key": api_key,
        "timeout": timeout,
        "stream": False,
        "num_retries": 0,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.max_output_tokens is not None:
        payload["max_tokens"] = request.max_output_tokens
    if base_url is not None:
        payload["api_base"] = base_url
    return payload


def normalize_response(raw: Any, *, provider: str, model: str) -> LLMResponse:
    """Normalize a raw provider response into a neutral ``LLMResponse``."""
    choices = getattr(raw, "choices", None)
    if not choices:
        raise AdapterResponseError("provider returned no choices", provider=provider, model=model)
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    if not isinstance(content, str):
        raise AdapterResponseError(
            "provider response had no text content", provider=provider, model=model
        )
    return LLMResponse(
        text=content,
        provider=provider,
        model=model,
        usage=_normalize_usage(getattr(raw, "usage", None), provider=provider, model=model),
        finish_reason=_map_finish_reason(getattr(choices[0], "finish_reason", None)),
    )


def _map_finish_reason(value: object) -> FinishReason:
    if isinstance(value, str):
        return _FINISH_REASONS.get(value, FinishReason.UNKNOWN)
    return FinishReason.UNKNOWN


def _coerce_token(value: object, *, provider: str, model: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AdapterResponseError(
            "provider returned an invalid token count", provider=provider, model=model
        )
    return value


def _normalize_usage(usage: Any, *, provider: str, model: str) -> ModelUsage:
    if usage is None:
        return ModelUsage.unavailable()
    raw_in = getattr(usage, "prompt_tokens", None)
    raw_out = getattr(usage, "completion_tokens", None)
    if raw_in is None or raw_out is None:
        # Partial/unusable usage is reported honestly, never zero-filled.
        return ModelUsage.unavailable()
    tokens_in = _coerce_token(raw_in, provider=provider, model=model)
    tokens_out = _coerce_token(raw_out, provider=provider, model=model)
    raw_total = getattr(usage, "total_tokens", None)
    if raw_total is not None:
        total = _coerce_token(raw_total, provider=provider, model=model)
        if total != tokens_in + tokens_out:
            raise AdapterResponseError(
                "provider usage total is inconsistent", provider=provider, model=model
            )
    try:
        return ModelUsage(
            UsageStatus.MEASURED,
            TokenCount(tokens_in),
            TokenCount(tokens_out),
            TokenCount(tokens_in + tokens_out),
        )
    except InvariantViolation as exc:
        raise AdapterResponseError(str(exc), provider=provider, model=model) from None
