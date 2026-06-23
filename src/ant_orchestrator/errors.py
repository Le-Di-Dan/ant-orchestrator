"""Neutral base exception for the whole package.

Intentionally minimal and stdlib-only. It must not import any internal package so
every layer can derive its own errors from a common root without coupling
(see ``docs/plans/PHASE_1_PLAN.md`` §14).
"""

from __future__ import annotations


class AntError(Exception):
    """Base class for every Ant-Orchestrator error."""
