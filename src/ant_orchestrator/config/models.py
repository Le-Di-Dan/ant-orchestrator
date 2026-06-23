"""Typed, immutable configuration models (PHASE_1_PLAN §11.1)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Project-identity configuration."""

    name: str


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Fully resolved configuration after applying precedence."""

    version: int
    project: ProjectConfig
