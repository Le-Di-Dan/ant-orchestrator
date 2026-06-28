"""Thin re-export shim — Phase 4 CLI commands import from here for backward compat.

All assembly logic has moved to :mod:`ant_orchestrator.composition` (neutral root).
This module only re-exports the public names so existing CLI code requires no change.
"""

from ant_orchestrator.composition import (  # noqa: F401
    WorkflowServices as WorkflowServices,
)
from ant_orchestrator.composition import (
    build_workflow_services as build_workflow_services,
)
