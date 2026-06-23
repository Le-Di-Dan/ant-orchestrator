"""Workspace layout constants — single source of truth (PHASE_1_PLAN §12.1/§17)."""

from __future__ import annotations

from typing import Final

ANT_DIRNAME: Final = ".ant"
MARKER_FILENAME: Final = "workspace.json"
DATABASE_FILENAME: Final = "state.sqlite"
GITIGNORE_FILENAME: Final = ".gitignore"

WORKSPACE_FORMAT_VERSION: Final = 1

SUBDIRECTORIES: Final = (
    "tasks",
    "memory",
    "pheromones",
    "logs",
    "cache",
    "snapshots",
    "handoff",
)

# Directories tracked in git (kept non-empty with a .gitkeep) — D18 (APPROVED).
GITKEEP_DIRS: Final = ("tasks",)

# Contents of ``.ant/.gitignore`` — track config/marker/tasks, ignore the rest.
GITIGNORE_LINES: Final = (
    DATABASE_FILENAME,
    f"{DATABASE_FILENAME}-wal",
    f"{DATABASE_FILENAME}-shm",
    "memory/",
    "pheromones/",
    "handoff/",
    "logs/",
    "cache/",
    "snapshots/",
)

# Marker JSON keys.
MARKER_KEY_ID: Final = "workspace_id"
MARKER_KEY_VERSION: Final = "workspace_format_version"
MARKER_KEY_CREATED_AT: Final = "created_at"

# Naming for atomic staging artifacts.
STAGING_PREFIX: Final = ".ant.tmp-"
DB_TEMP_SUFFIX: Final = ".tmp-"
