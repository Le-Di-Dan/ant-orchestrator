"""Timeout policy: a single resolution function with one precedence (PHASE_2_PLAN §5).

Precedence: ``request timeout > endpoint timeout > system default``. All timeouts
are ``float`` so they line up directly with ``LLMRequest.timeout_seconds``
(float | None) — adapters use the resolver output as-is, with no conversion.

Values must be a finite, positive number ``<= MAX_TIMEOUT_SECONDS``. Booleans,
NaN and infinities are rejected; out-of-range values are rejected — never clamped,
rounded or coerced to ``int``. Invalid *configuration* timeouts raise
:class:`ConfigInvalid`; this is unrelated to ``AdapterTimeoutError``, which
represents an invocation that actually timed out.
"""

from __future__ import annotations

import math

from ant_orchestrator.config.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
)
from ant_orchestrator.config.errors import ConfigInvalid


def validate_timeout(value: float, *, scope: str = "timeout_seconds") -> float:
    """Return ``value`` as a valid ``float`` timeout, else raise ``ConfigInvalid``.

    Rejects booleans, NaN, ``±inf``, non-positive values and values above
    :data:`MAX_TIMEOUT_SECONDS`. The value is not clamped, rounded or truncated.
    """
    if isinstance(value, bool):
        raise ConfigInvalid(f"{scope} must be a number, not a boolean")
    numeric = float(value)
    if math.isnan(numeric) or math.isinf(numeric):
        raise ConfigInvalid(f"{scope} must be a finite number")
    if numeric <= 0:
        raise ConfigInvalid(f"{scope} must be > 0")
    if numeric > MAX_TIMEOUT_SECONDS:
        raise ConfigInvalid(f"{scope} must be <= {MAX_TIMEOUT_SECONDS}")
    return numeric


def resolve_timeout(
    request_timeout_seconds: float | None,
    endpoint_timeout_seconds: float | None,
) -> float:
    """Resolve a single, valid ``float`` timeout by precedence (no clamping).

    Falls back to :data:`DEFAULT_TIMEOUT_SECONDS` when both inputs are ``None``.
    The result is always a valid timeout.
    """
    if request_timeout_seconds is not None:
        return validate_timeout(request_timeout_seconds, scope="request timeout")
    if endpoint_timeout_seconds is not None:
        return validate_timeout(endpoint_timeout_seconds, scope="endpoint timeout")
    return DEFAULT_TIMEOUT_SECONDS
