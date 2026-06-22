"""Smoke tests verifying the package and its subpackages import successfully."""

import importlib

SUBPACKAGES = (
    "api",
    "cli",
    "core",
    "workflows",
    "adapters",
    "workers",
    "context",
    "memory",
    "energy",
    "tools",
    "config",
)


def test_root_package_imports() -> None:
    """The root package can be imported via the editable installation."""
    importlib.import_module("ant_orchestrator")


def test_all_subpackages_import() -> None:
    """Every declared subpackage in PROJECT_STRUCTURE imports successfully."""
    for name in SUBPACKAGES:
        importlib.import_module(f"ant_orchestrator.{name}")
