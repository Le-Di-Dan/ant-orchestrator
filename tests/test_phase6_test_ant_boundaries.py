"""CP3 — TestAnt contract + import/security boundary audit (no Docker, §13.6)."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import ant_orchestrator
from ant_orchestrator.workers.test.ant import TestAnt

_WORKER_DIR = Path(ant_orchestrator.__file__).parent / "workers" / "test"

# The read-only worker package must never reach for these layers/modules.
_BANNED_MODULES = {
    "subprocess",
    "langgraph",
    "ant_orchestrator.adapters.container_isolation",
    "ant_orchestrator.adapters.container_argv",
    "ant_orchestrator.persistence",
    "ant_orchestrator.energy",
}
_BANNED_TOPS = {"subprocess", "langgraph", "litellm", "openai"}
# Constructor parameters that would grant write/Git/provider authority.
_FORBIDDEN_PARAM_HINTS = ("mutator", "git", "provider", "composer", "llm", "writer", "repository")


def _imported(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


def test_worker_does_not_import_banned_layers() -> None:
    for file in sorted(_WORKER_DIR.rglob("*.py")):
        for module in _imported(file):
            assert module.split(".")[0] not in _BANNED_TOPS, f"{file} imports {module}"
            for banned in _BANNED_MODULES:
                assert not (module == banned or module.startswith(banned + ".")), (
                    f"{file} imports banned {module}"
                )
            # The worker may know the Docker backend only via the abstract port.
            assert "ContainerIsolationBackend" not in module


def test_test_ant_constructor_has_no_mutation_authority() -> None:
    params = inspect.signature(TestAnt.__init__).parameters
    names = set(params) - {"self"}
    assert names == {
        "command_registry",
        "command_policy",
        "provisioner",
        "isolation",
        "classifier",
        "clock",
        "output_reader",
    }
    for name in names:
        assert not any(hint in name for hint in _FORBIDDEN_PARAM_HINTS), name


def test_worker_persistence_and_energy_free() -> None:
    # Defence in depth: no persistence/energy/provider symbol leaks via imports.
    blob = "\n".join(p.read_text(encoding="utf-8") for p in _WORKER_DIR.rglob("*.py"))
    for needle in ("EnergyMeasurement", "WorkerRunRepository", "LLMAdapter", "shell=True"):
        assert needle not in blob, needle
