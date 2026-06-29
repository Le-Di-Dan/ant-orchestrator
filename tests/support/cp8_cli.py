"""Test-only console entry for the CP8 subprocess restart suite.

Runs as ``python -m tests.support.cp8_cli <args>``. It is the *production* CLI
application (``ant_orchestrator.cli.main``) with exactly one dependency-injection
seam applied before dispatch: the ``run`` command's services factory is swapped to
the neutral deterministic-stub composition. This lets the full-restart E2E suite
drive ``run`` across real OS process boundaries with a deterministic worker — with
NO provider config, NO network and NO ``ANT_SELFTEST`` environment switch.

This module lives under ``tests/`` and is never imported by production code, so the
production ``ant``/``antctl`` console scripts cannot reach the stub through it. The
production ``run`` path always uses ``build_production_workflow_services`` (fail-
closed on missing provider config).
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.cli import phase4_commands
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services


def _stub_run_services(path: Path | None) -> WorkflowServices:
    """Neutral deterministic-stub composition (test-only DI for ``run``)."""
    return build_workflow_services(path if path is not None else Path.cwd())


# Apply the DI seam before the app is invoked. ``run`` resolves ``_run_services`` as
# a module global at call time, so replacing it here steers only this test process.
phase4_commands._run_services = _stub_run_services  # type: ignore[assignment]


def main() -> None:
    from ant_orchestrator.cli.main import app

    app()


if __name__ == "__main__":
    main()
