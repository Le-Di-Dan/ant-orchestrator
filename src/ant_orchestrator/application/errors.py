"""Application-layer errors (PHASE_1_PLAN §14)."""

from __future__ import annotations

from ant_orchestrator.errors import AntError


class ApplicationError(AntError):
    """Base class for application/use-case errors."""
