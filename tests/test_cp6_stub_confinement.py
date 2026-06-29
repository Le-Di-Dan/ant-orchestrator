"""CP6 — production stub confinement + version-source drift guard.

After CP6, the deterministic stub must NEVER be reachable from the production
``run`` command: not via config, not via any environment variable. Production ``run``
fails closed when provider config is missing instead of silently using the stub.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

import ant_orchestrator
from ant_orchestrator.cli import phase4_commands
from ant_orchestrator.cli.composition import build_services
from ant_orchestrator.cli.composition_production import _ProductionGuardWorker
from ant_orchestrator.config.constants import ANT_CLI_VERSION
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.workers.stub import DeterministicStubAdapter


def _init_nest(path: Path) -> None:
    build_services().init_nest.init(path)


def test_production_run_services_fail_closed_without_provider(tmp_path: Path) -> None:
    _init_nest(tmp_path)
    with pytest.raises(ConfigInvalid):
        phase4_commands._run_services(tmp_path)


def test_ant_selftest_env_does_not_switch_run_to_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _init_nest(tmp_path)
    # The legacy switch must be inert: setting it must NOT yield a stub composition;
    # production still fails closed on the missing provider config.
    monkeypatch.setenv("ANT_SELFTEST", "1")
    with pytest.raises(ConfigInvalid):
        phase4_commands._run_services(tmp_path)


def test_phase4_commands_source_has_no_stub_switch() -> None:
    source = Path(phase4_commands.__file__).read_text(encoding="utf-8")
    assert "ANT_SELFTEST" not in source
    assert "os.environ" not in source


def test_production_guard_worker_is_not_the_stub() -> None:
    assert not isinstance(_ProductionGuardWorker(), DeterministicStubAdapter)


def test_production_source_does_not_construct_stub_in_run_path() -> None:
    prod = Path(ant_orchestrator.__file__).parent / "cli" / "composition_production.py"
    text = prod.read_text(encoding="utf-8")
    # The name may appear in a docstring forbidding it, but it must never be imported
    # or constructed in the production composition.
    assert "DeterministicStubAdapter(" not in text
    assert "import DeterministicStubAdapter" not in text


# --- version source drift guard (Strategy C) ----------------------------------


def test_pyproject_version_matches_cli_version_constant() -> None:
    root = Path(ant_orchestrator.__file__).parents[2]
    pyproject = root / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    assert data["project"]["version"] == ANT_CLI_VERSION, (
        "pyproject [project].version drifted from ANT_CLI_VERSION; keep them in sync"
    )
