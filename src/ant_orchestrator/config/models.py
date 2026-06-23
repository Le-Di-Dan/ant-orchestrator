"""Typed, immutable configuration models (PHASE_1_PLAN §11.1, PHASE_2_PLAN §4)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Project-identity configuration."""

    name: str


@dataclass(frozen=True, slots=True)
class ModelEndpointConfig:
    """A provider-neutral model endpoint (no secret/api-key, no monetary cost).

    ``provider`` and ``model`` are required, opaque strings (validated by the
    resolver). ``base_url`` lets a local endpoint (e.g. Ollama) be configured
    without a future schema change. ``timeout_seconds`` is an optional per-endpoint
    override resolved against the system default at invocation time.
    """

    provider: str
    model: str
    timeout_seconds: float | None = None
    base_url: str | None = None


@dataclass(frozen=True, slots=True)
class ModelsConfig:
    """Optional model-endpoint roles. Empty when the document omits ``models``."""

    queen: ModelEndpointConfig | None = None
    local: ModelEndpointConfig | None = None


@dataclass(frozen=True, slots=True)
class ResolvedConfig:
    """Fully resolved configuration after applying precedence."""

    version: int
    project: ProjectConfig
    models: ModelsConfig = field(default_factory=ModelsConfig)
