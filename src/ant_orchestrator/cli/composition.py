"""Composition root: wire concrete adapters into application services.

This is the only module that knows every layer; it provides the production Clock
and IdGenerator implementations and assembles the use-case services.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from ant_orchestrator.application.services.init_nest import InitNestService
from ant_orchestrator.application.services.nest_status import GetNestStatusService
from ant_orchestrator.application.services.show_config import ShowResolvedConfigService
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
