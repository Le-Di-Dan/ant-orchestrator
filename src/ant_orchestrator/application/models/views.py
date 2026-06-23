"""Read-only views rendered by the CLI delivery layer."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ant_orchestrator.application.models.nest_state import NestState
from ant_orchestrator.config.models import ResolvedConfig


@dataclass(frozen=True, slots=True)
class NestStatusView:
    """Observable status of a discovered Nest."""

    root: Path
    state: NestState
    workspace_format_version: int | None
    schema_version: int | None


@dataclass(frozen=True, slots=True)
class ResolvedConfigView:
    """Resolved configuration for a Nest, with its root path."""

    root: Path
    config: ResolvedConfig
