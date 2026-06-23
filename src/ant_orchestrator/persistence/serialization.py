"""Row (de)serialization helpers shared by SQLite repositories (PHASE_1_PLAN §13.3)."""

from __future__ import annotations

import json
from collections.abc import Mapping

from ant_orchestrator.core.domain.value_objects import UtcTimestamp


def dump_str_tuple(values: tuple[str, ...]) -> str:
    """Serialize a tuple of strings as a JSON array."""
    return json.dumps(list(values))


def load_str_tuple(text: str | None) -> tuple[str, ...]:
    """Parse a JSON array of strings (``None`` → empty tuple)."""
    if text is None:
        return ()
    return tuple(str(item) for item in json.loads(text))


def dump_payload(payload: Mapping[str, object]) -> str:
    """Serialize a checkpoint payload to canonical, stable JSON (D33)."""
    return json.dumps(dict(payload), sort_keys=True, ensure_ascii=False)


def load_payload(text: str) -> dict[str, object]:
    """Parse a checkpoint payload JSON object."""
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("checkpoint payload must be a JSON object")
    return {str(key): value for key, value in data.items()}


def iso_or_none(timestamp: UtcTimestamp | None) -> str | None:
    """Render an optional timestamp as ISO-8601, or ``None``."""
    return timestamp.to_iso() if timestamp is not None else None


def parse_iso_or_none(text: str | None) -> UtcTimestamp | None:
    """Parse an optional ISO-8601 string into a timestamp, or ``None``."""
    return UtcTimestamp.from_iso(text) if text is not None else None
