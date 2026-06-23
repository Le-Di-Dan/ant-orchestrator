"""Configuration constants — single source of truth (PHASE_1_PLAN §11)."""

from __future__ import annotations

from typing import Final

# Config DOCUMENT version (distinct from workspace format & DB schema version, D12).
CONFIG_DOCUMENT_VERSION: Final = 1

CONFIG_FILENAME: Final = "config.yaml"
DEFAULT_PROJECT_NAME: Final = "unnamed"

# Environment overrides (only string-valued fields, to avoid coercion — §11.6).
ENV_PREFIX: Final = "ANT_"
ENV_PROJECT_NAME: Final = "ANT_PROJECT_NAME"

# Document keys and their allowed sets (unknown keys rejected at every level).
KEY_VERSION: Final = "version"
KEY_PROJECT: Final = "project"
KEY_PROJECT_NAME: Final = "name"
ALLOWED_TOP_LEVEL_KEYS: Final = frozenset({KEY_VERSION, KEY_PROJECT})
ALLOWED_PROJECT_KEYS: Final = frozenset({KEY_PROJECT_NAME})
