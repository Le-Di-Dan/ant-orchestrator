"""Sanitized operational logging for model adapters (CP3).

Logs only non-sensitive operational metadata. It never logs prompts, messages,
model output, secrets/API keys, base URLs, headers, raw exceptions or raw
responses. Uses the standard library logger; no third-party observability.
"""

from __future__ import annotations

import logging

from ant_orchestrator.application.ports.llm import ModelUsage, UsageStatus

_logger = logging.getLogger("ant_orchestrator.adapters.llm")


def log_success(
    *,
    provider: str,
    model: str,
    duration_ms: float,
    usage: ModelUsage,
    finish_reason: str,
) -> None:
    """Log a successful completion with measured token counts when available."""
    if usage.status is UsageStatus.MEASURED and usage.tokens_in is not None:
        tokens = (
            f" tokens_in={usage.tokens_in.value}"
            f" tokens_out={usage.tokens_out.value if usage.tokens_out else 0}"
            f" tokens_total={usage.tokens_total.value if usage.tokens_total else 0}"
        )
    else:
        tokens = ""
    _logger.info(
        "llm.complete.success provider=%s model=%s duration_ms=%.1f usage=%s finish=%s%s",
        provider,
        model,
        duration_ms,
        usage.status.value,
        finish_reason,
        tokens,
    )


def log_failure(
    *,
    provider: str,
    model: str,
    duration_ms: float,
    error_code: str,
    retryable: bool,
) -> None:
    """Log a failed completion with the neutral error code only."""
    _logger.info(
        "llm.complete.failure provider=%s model=%s duration_ms=%.1f error=%s retryable=%s",
        provider,
        model,
        duration_ms,
        error_code,
        retryable,
    )
