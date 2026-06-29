"""Re-export shim: production workflow composition (Phase 8 CP3).

The real implementation lives in :mod:`ant_orchestrator.cli.composition_production`
(the CLI edge layer that is permitted to wire concrete adapter implementations).
This module re-exports the public API for callers outside the CLI layer.
"""

from ant_orchestrator.cli.composition_production import (  # noqa: F401
    build_production_workflow_services,
    validate_production_config,
)
