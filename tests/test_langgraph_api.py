"""Dependency/API verification for the pinned LangGraph version (CP3)."""

from __future__ import annotations

import inspect
from importlib.metadata import version
from pathlib import Path

import ant_orchestrator

PKG_ROOT = Path(ant_orchestrator.__file__).parent


def test_pinned_versions_are_satisfied() -> None:
    assert version("langgraph").startswith("1.2")
    cp = tuple(int(p) for p in version("langgraph-checkpoint-sqlite").split(".")[:2])
    assert cp >= (3, 0)


def test_invoke_supports_explicit_durability() -> None:
    from langgraph.graph.state import CompiledStateGraph

    params = inspect.signature(CompiledStateGraph.invoke).parameters
    assert "durability" in params


def test_command_supports_resume_mapping() -> None:
    from langgraph.types import Command

    assert "resume" in Command.__dataclass_fields__


def test_state_snapshot_exposes_tasks_and_interrupts() -> None:
    from langgraph.types import StateSnapshot

    assert "tasks" in StateSnapshot._fields
    assert "interrupts" in StateSnapshot._fields


def test_interrupt_id_attribute_is_available() -> None:
    from langgraph.types import Interrupt

    # CP4 reads Interrupt.id (the deprecated .interrupt_id must not be used).
    assert "id" in getattr(Interrupt, "__annotations__", {})


def test_source_never_uses_deprecated_interrupt_id() -> None:
    for file in PKG_ROOT.rglob("*.py"):
        assert ".interrupt_id" not in file.read_text(encoding="utf-8"), (
            f"{file} uses deprecated .interrupt_id (use Interrupt.id)"
        )


def test_default_serializer_has_no_pickle_fallback() -> None:
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    assert JsonPlusSerializer().pickle_fallback is False
