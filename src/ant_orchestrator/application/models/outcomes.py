"""Outcomes returned by application services (not exceptions)."""

from __future__ import annotations

from enum import Enum


class InitNestOutcome(Enum):
    """Result of a successful ``ant init`` invocation."""

    CREATED = "created"
    PROVISIONED = "provisioned"
    ALREADY_INITIALIZED = "already_initialized"
