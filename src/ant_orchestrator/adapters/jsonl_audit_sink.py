"""JSONL audit sink — the MVP :class:`AuditSink` adapter (CP0).

Writes one redacted JSON object per line to ``.ant/logs/audit-<UTC-date>.jsonl``.
Stdlib only (no logging/observability framework). Every ``detail`` value is passed
through a :class:`Redactor` before serialization so no secret can reach disk, and
enums are serialized by their stable ``value`` (never ``repr``). This is one
adapter behind the :class:`AuditSink` port; future sinks (SQLite/remote) can
replace it without touching policy or application code.
"""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.application.ports.audit import AuditEvent
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.security.redaction.redactor import Redactor

_AUDIT_FILE_PREFIX = "audit-"
_AUDIT_FILE_SUFFIX = ".jsonl"


class JsonlAuditSink:
    """Append-only JSONL AuditSink writing redacted events under a logs directory."""

    def __init__(self, logs_dir: Path, *, clock: Clock, redactor: Redactor) -> None:
        self._logs_dir = logs_dir
        self._clock = clock
        self._redactor = redactor

    def write(self, event: AuditEvent) -> None:
        """Append one redacted JSON line for ``event`` to today's audit file."""
        line = json.dumps(self._serialize(event), sort_keys=True, ensure_ascii=False)
        path = self._current_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    def _current_path(self) -> Path:
        day = self._clock.now().value.date().isoformat()
        return self._logs_dir / f"{_AUDIT_FILE_PREFIX}{day}{_AUDIT_FILE_SUFFIX}"

    def _serialize(self, event: AuditEvent) -> dict[str, object]:
        decision = event.decision.value if event.decision is not None else None
        return {
            "schema_version": event.schema_version,
            "event_type": event.event_type.value,
            "decision": decision,
            "correlation_id": str(event.correlation_id),
            "created_at": event.created_at.to_iso(),
            "detail": {
                key: self._redactor.redact(value).text for key, value in event.detail.items()
            },
        }
