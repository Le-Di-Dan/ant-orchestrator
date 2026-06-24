"""AST import-boundary test for the infra-free inner layers (DoD §21.6)."""

from __future__ import annotations

import ast
from pathlib import Path

import ant_orchestrator

PKG_ROOT = Path(ant_orchestrator.__file__).parent
BANNED_EXTERNAL = {"sqlite3", "yaml", "typer", "langgraph", "litellm", "openai"}


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


# --- CP3: provider-SDK isolation ---------------------------------------------

PROVIDER_SDKS = {"litellm", "openai"}


def _top_imports(path: Path) -> set[str]:
    return {module.split(".")[0] for module in _imported_modules(path)}


def test_config_does_not_import_provider_or_adapters() -> None:
    for file in _files("config"):
        modules = _imported_modules(file)
        assert not ({m.split(".")[0] for m in modules} & PROVIDER_SDKS), (
            f"{file} imports provider SDK"
        )
        for module in modules:
            assert not module.startswith("ant_orchestrator.adapters"), f"{file} imports adapters"


def test_litellm_imported_only_in_adapters() -> None:
    adapters_dir = PKG_ROOT / "adapters"
    for file in PKG_ROOT.rglob("*.py"):
        if "litellm" in _top_imports(file):
            assert file.is_relative_to(adapters_dir), f"{file} imports litellm outside adapters"


def test_no_direct_openai_import_in_src() -> None:
    for file in PKG_ROOT.rglob("*.py"):
        assert "openai" not in _top_imports(file), f"{file} imports the openai SDK directly"


def test_no_ollama_sdk_import_in_src() -> None:
    for file in PKG_ROOT.rglob("*.py"):
        assert "ollama" not in _top_imports(file), f"{file} imports the ollama SDK directly"


def test_cloud_and_local_adapters_do_not_import_each_other() -> None:
    cloud = _imported_modules(PKG_ROOT / "adapters" / "litellm_cloud.py")
    local = _imported_modules(PKG_ROOT / "adapters" / "ollama_local.py")
    assert "ant_orchestrator.adapters.ollama_local" not in cloud
    assert "ant_orchestrator.adapters.litellm_cloud" not in local


def test_fake_llm_support_is_provider_free() -> None:
    fake = Path(__file__).parent / "support" / "fake_llm.py"
    assert not (_top_imports(fake) & PROVIDER_SDKS), "fake_llm.py imports a provider SDK"


# --- CP5: tool ports declare contracts only (no real execution libs) ---------

REAL_EXECUTION_LIBS = {"subprocess", "git", "dulwich", "gitpython", "pygit2"}


def test_no_real_execution_libraries_in_src() -> None:
    for file in PKG_ROOT.rglob("*.py"):
        leaked = _top_imports(file) & REAL_EXECUTION_LIBS
        assert not leaked, f"{file} imports a real-execution library {leaked}"
