"""JSONL audit log reader — bounded, newest-first traversal (Phase 7 CP3).

Algorithm (per plan C.9):
  1. List ``audit-YYYY-MM-DD.jsonl`` files, sort newest-first by filename.
  2. For each file, read ALL lines (oldest-first within file), parse, filter,
     reverse (newest-first within file), then extend the accumulation buffer.
  3. Stop early when buffer reaches ``limit + 1`` (enough to confirm has_more).
  4. Return the first ``limit`` events; ``has_more = len(buffer) > limit``.

Memory complexity: O(limit) — only one daily file's worth of matching lines is
retained at a time before being appended to a buffer capped at limit+1.

Corrupt JSON lines are skipped and counted. Unreadable files raise
``StorageIntegrityError`` (fail-closed).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from ant_orchestrator.application.ports.audit import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    CorrelationId,
)
from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage, AuditLogQuery
from ant_orchestrator.application.ports.database import StorageIntegrityError
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.value_objects import UtcTimestamp

_AUDIT_PREFIX = "audit-"
_AUDIT_SUFFIX = ".jsonl"
_DATE_LEN = len("YYYY-MM-DD")


class JsonlAuditLogReader:
    """Reads bounded newest-first audit events from daily JSONL files."""

    def __init__(self, logs_dir: Path) -> None:
        self._logs_dir = logs_dir

    def read(self, query: AuditLogQuery) -> AuditLogPage:
        files = _sorted_audit_files(self._logs_dir)
        buffer: list[AuditEvent] = []
        corrupt_count = 0
        files_scanned = 0
        want = query.limit + 1
        since_date = query.since.date() if query.since is not None else None

        for file_path in files:
            file_date = _parse_file_date(file_path.name)
            if file_date is None:
                continue
            if since_date is not None and file_date < since_date:
                break

            try:
                raw_lines = file_path.read_text(encoding="utf-8").splitlines()
            except OSError as exc:
                raise StorageIntegrityError(f"audit file unreadable: {file_path}") from exc

            files_scanned += 1
            matching: list[AuditEvent] = []
            for line in raw_lines:
                line = line.strip()
                if not line:
                    continue
                event, is_corrupt = _parse_line(line)
                if is_corrupt:
                    corrupt_count += 1
                    continue
                if event is None:
                    continue
                if not _matches(event, query):
                    continue
                matching.append(event)

            matching.reverse()
            buffer.extend(matching)

            if len(buffer) >= want:
                break

        has_more = len(buffer) > query.limit
        return AuditLogPage(
            events=tuple(buffer[: query.limit]),
            corrupt_count=corrupt_count,
            files_scanned=files_scanned,
            has_more=has_more,
        )


def _sorted_audit_files(logs_dir: Path) -> list[Path]:
    if not logs_dir.exists():
        return []
    files = [
        f
        for f in logs_dir.iterdir()
        if f.is_file() and f.name.startswith(_AUDIT_PREFIX) and f.name.endswith(_AUDIT_SUFFIX)
    ]
    return sorted(files, key=lambda f: f.name, reverse=True)


def _parse_file_date(name: str) -> date | None:
    stem = name.removesuffix(_AUDIT_SUFFIX)
    if not stem.startswith(_AUDIT_PREFIX):
        return None
    date_str = stem[len(_AUDIT_PREFIX) :]
    if len(date_str) != _DATE_LEN:
        return None
    try:
        return date.fromisoformat(date_str)
    except ValueError:
        return None


def _parse_line(line: str) -> tuple[AuditEvent | None, bool]:
    try:
        raw = json.loads(line)
    except json.JSONDecodeError:
        return None, True
    if not isinstance(raw, dict):
        return None, True
    event = _to_audit_event(raw)
    if event is None:
        return None, True
    return event, False


def _to_audit_event(raw: dict[str, object]) -> AuditEvent | None:
    try:
        if raw.get("schema_version") != AUDIT_SCHEMA_VERSION:
            return None
        event_type = AuditEventType(raw["event_type"])
        correlation_id = CorrelationId(str(raw["correlation_id"]))
        created_at = UtcTimestamp.from_iso(str(raw["created_at"]))
        raw_detail = raw.get("detail", {})
        if not isinstance(raw_detail, dict):
            return None
        detail: dict[str, str] = {}
        for k, v in raw_detail.items():
            if not isinstance(k, str) or not isinstance(v, str):
                return None
            detail[k] = v
        raw_decision = raw.get("decision")
        decision = PolicyDecision(raw_decision) if raw_decision is not None else None
        return AuditEvent(
            event_type=event_type,
            correlation_id=correlation_id,
            created_at=created_at,
            detail=detail,
            decision=decision,
        )
    except Exception:
        return None


def _matches(event: AuditEvent, query: AuditLogQuery) -> bool:
    if query.task_id is not None:
        if event.detail.get("task_id") != query.task_id:
            return False
    if query.since is not None:
        if event.created_at.value < query.since:
            return False
    return True
