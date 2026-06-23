"""Nest discovery: walk up from a directory to the nearest ``.ant/`` (PHASE_1_PLAN §12.5)."""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.application.ports.workspace import NestNotFound
from ant_orchestrator.workspace.layout import ANT_DIRNAME


def find_nest(start: Path) -> Path | None:
    """Return the nearest ancestor (incl. ``start``) containing ``.ant/``, else None."""
    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / ANT_DIRNAME).is_dir():
            return candidate
    return None


def find_ancestor_nest(target: Path) -> Path | None:
    """Return the nearest *strict* ancestor of ``target`` containing ``.ant/``, else None."""
    resolved = target.resolve()
    for candidate in resolved.parents:
        if (candidate / ANT_DIRNAME).is_dir():
            return candidate
    return None


def discover(start: Path) -> Path:
    """Return the project root containing a Nest; raise ``NestNotFound`` if none."""
    root = find_nest(start)
    if root is None:
        raise NestNotFound(f"No {ANT_DIRNAME}/ found from {start}")
    return root
