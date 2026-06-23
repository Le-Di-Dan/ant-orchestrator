"""Atomic filesystem primitives for workspace publishing (PHASE_1_PLAN §12.4)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def publish(source: Path, target: Path) -> None:
    """Atomically move ``source`` onto ``target`` (single rename)."""
    os.replace(source, target)


def discard(path: Path) -> None:
    """Best-effort removal of a staging file or directory; never raises."""
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
    elif path.exists():
        try:
            path.unlink()
        except OSError:
            pass
