"""AST import-boundary test for the infra-free inner layers (DoD §21.6)."""

from __future__ import annotations

import ast
from pathlib import Path

import ant_orchestrator

PKG_ROOT = Path(ant_orchestrator.__file__).parent
BANNED_EXTERNAL = {"sqlite3", "yaml", "typer", "langgraph", "litellm"}


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            modules.add(node.module)
    return modules


def _files(relative: str) -> list[Path]:
    return sorted((PKG_ROOT / relative).rglob("*.py"))


def _assert_layer(relative: str, allowed_internal: tuple[str, ...]) -> None:
    for file in _files(relative):
        for module in _imported_modules(file):
            top = module.split(".")[0]
            assert top not in BANNED_EXTERNAL, f"{file} imports banned {module}"
            if module.startswith("ant_orchestrator"):
                ok = any(
                    module == prefix or module.startswith(prefix + ".")
                    for prefix in allowed_internal
                )
                assert ok, f"{file} imports disallowed internal {module}"


def test_core_domain_is_infra_free() -> None:
    _assert_layer(
        "core/domain",
        ("ant_orchestrator.errors", "ant_orchestrator.core.domain"),
    )


def test_core_ports_is_infra_free() -> None:
    _assert_layer(
        "core/ports",
        ("ant_orchestrator.errors", "ant_orchestrator.core.domain", "ant_orchestrator.core.ports"),
    )


def test_application_ports_is_infra_free() -> None:
    _assert_layer(
        "application/ports",
        (
            "ant_orchestrator.errors",
            "ant_orchestrator.core.domain",
            "ant_orchestrator.application.ports",
        ),
    )


def test_application_services_no_adapter_imports() -> None:
    _assert_layer(
        "application/services",
        (
            "ant_orchestrator.errors",
            "ant_orchestrator.core.domain",
            "ant_orchestrator.core.ports",
            "ant_orchestrator.application.ports",
            "ant_orchestrator.application.models",
            "ant_orchestrator.application.services",
            "ant_orchestrator.application.errors",
            "ant_orchestrator.config",
        ),
    )
