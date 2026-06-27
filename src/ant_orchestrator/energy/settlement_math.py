"""Shared, honest consumption accounting for worker energy settlement (PHASE_5_PLAN).

Both the single-process CP5 lifecycle and the CP6 durable lifecycle settle consumption
the same way: a measured total (or in+out) is charged exactly, while ``UNAVAILABLE`` usage
falls back conservatively to the reserved amount — never zero. Keeping the rule in one
place guarantees a fresh settlement and a recovery replay compute the identical charge.
"""

from __future__ import annotations

from ant_orchestrator.application.ports.llm import ModelUsage, UsageStatus


def compute_consumption(usage: ModelUsage, reserved: int) -> tuple[int, bool]:
    """Return ``(actual_tokens, fallback_used)`` for one settlement.

    ``fallback_used`` is True iff usage was ``UNAVAILABLE`` and the reserved amount was
    charged conservatively instead of a measured value.
    """
    if usage.status is UsageStatus.UNAVAILABLE:
        return reserved, True
    if usage.tokens_total is not None:
        return usage.tokens_total.value, False
    tin = usage.tokens_in.value if usage.tokens_in is not None else 0
    tout = usage.tokens_out.value if usage.tokens_out is not None else 0
    return tin + tout, False
