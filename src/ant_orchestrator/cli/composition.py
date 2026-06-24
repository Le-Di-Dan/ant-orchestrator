"""Composition root: wire concrete adapters into application services.

This is the only module that knows every layer; it provides the production Clock
and IdGenerator implementations and assembles the use-case services.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ant_orchestrator.adapters.env_secret_provider import EnvSecretProvider
from ant_orchestrator.adapters.factory import build_llm_adapter
from ant_orchestrator.adapters.litellm_client import LiteLLMSdkClient
from ant_orchestrator.application.ports.llm import LLMAdapter
from ant_orchestrator.application.services.init_nest import InitNestService
from ant_orchestrator.application.services.nest_status import GetNestStatusService
from ant_orchestrator.application.services.show_config import ShowResolvedConfigService
from ant_orchestrator.config.models import ModelEndpointConfig, ResolvedConfig
from ant_orchestrator.config.resolver import ConfigResolver
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.migrations import (
    SqliteDatabaseBootstrapper,
    SqliteDatabaseInspector,
)
from ant_orchestrator.workspace.nest import FilesystemWorkspaceProvisioner


class SystemClock:
    """Production Clock backed by the system UTC time."""

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(datetime.now(UTC))


class Uuid4IdGenerator:
    """Production IdGenerator backed by UUID4."""

    def new_id(self) -> str:
        return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class Services:
    """Container for the Phase 1 application services."""

    init_nest: InitNestService
    nest_status: GetNestStatusService
    show_config: ShowResolvedConfigService


def build_services() -> Services:
    """Assemble production services with their concrete adapters."""
    clock = SystemClock()
    provisioner = FilesystemWorkspaceProvisioner(clock, Uuid4IdGenerator())
    bootstrapper = SqliteDatabaseBootstrapper(clock)
    inspector = SqliteDatabaseInspector()
    return Services(
        init_nest=InitNestService(provisioner, bootstrapper, inspector),
        nest_status=GetNestStatusService(provisioner, inspector),
        show_config=ShowResolvedConfigService(provisioner, ConfigResolver(), dict(os.environ)),
    )


@dataclass(frozen=True, slots=True)
class ConfiguredLLMAdapters:
    """Model adapters assembled from config.

    A slot is ``None`` when its endpoint is absent from ``models`` (a Phase 1
    config without a ``models`` section yields two ``None`` slots). Roles are not
    bound to a provider here — the factory chooses the adapter from each
    endpoint's ``provider``.
    """

    queen: LLMAdapter | None = None
    local: LLMAdapter | None = None


def build_configured_llm_adapters(config: ResolvedConfig) -> ConfiguredLLMAdapters:
    """Construct LLM adapters for the configured endpoints.

    Wires the production :class:`EnvSecretProvider` and :class:`LiteLLMSdkClient`
    into the factory. This only constructs objects: no network call, no secret
    lookup and no provider ping happen here.
    """
    secret_provider = EnvSecretProvider()
    completion_client = LiteLLMSdkClient()

    def _build(endpoint: ModelEndpointConfig | None) -> LLMAdapter | None:
        if endpoint is None:
            return None
        return build_llm_adapter(
            endpoint,
            secret_provider=secret_provider,
            completion_client=completion_client,
        )

    return ConfiguredLLMAdapters(
        queen=_build(config.models.queen),
        local=_build(config.models.local),
    )
