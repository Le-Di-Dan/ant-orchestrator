"""YAML config document loading and dumping (PHASE_1_PLAN §11.3).

Uses ``yaml.safe_load`` only; no custom tags. A missing file yields an empty
document (defaults). Parsing/IO failures and non-mapping roots raise ``ConfigInvalid``.
The loader never rewrites the user's file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from ant_orchestrator.config.constants import (
    KEY_PROJECT,
    KEY_PROJECT_NAME,
    KEY_VERSION,
)
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.models import ResolvedConfig


def load_document(path: Path) -> dict[str, object]:
    """Load a config document as a string-keyed mapping; ``{}`` if file absent."""
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigInvalid(f"Cannot read config at {path}: {exc}") from exc
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigInvalid("Config root must be a mapping")
    return as_str_keyed(data)


def as_str_keyed(data: dict[object, object]) -> dict[str, object]:
    """Return a copy of ``data`` ensuring every key is a string."""
    result: dict[str, object] = {}
    for key, value in data.items():
        if not isinstance(key, str):
            raise ConfigInvalid(f"Config keys must be strings, got {key!r}")
        result[key] = value
    return result


def dump_document(config: ResolvedConfig) -> str:
    """Render a resolved config as canonical YAML text (UTF-8)."""
    data = {
        KEY_VERSION: config.version,
        KEY_PROJECT: {KEY_PROJECT_NAME: config.project.name},
    }
    return yaml.safe_dump(data, sort_keys=True, allow_unicode=True)
