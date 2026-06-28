"""JsonlAuditLogReader — ordering, pagination, newest-first traversal (T1-T5, T7-T8, T15)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.application.ports.audit import AUDIT_SCHEMA_VERSION
from ant_orchestrator.application.ports.audit_log_reader import AuditLogQuery

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _event_line(
    correlation_id: str = "corr-1",
    offset_seconds: int = 0,
    task_id: str | None = None,
    created_at: str | None = None,
) -> str:
    ts = (_BASE_TS + timedelta(seconds=offset_seconds)).isoformat()
    if created_at is not None:
        ts = created_at
    detail: dict[str, str] = {}
    if task_id is not None:
        detail["task_id"] = task_id
    return json.dumps(
        {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "event_type": "path_decision",
            "correlation_id": correlation_id,
            "created_at": ts,
            "detail": detail,
            "decision": None,
        },
        sort_keys=True,
    )


def _write(logs_dir: Path, date_str: str, lines: list[str]) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    (logs_dir / f"audit-{date_str}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _query(limit: int = 10, task_id: str | None = None, since: datetime | None = None) -> AuditLogQuery:
    return AuditLogQuery(task_id=task_id, limit=limit, since=since)


# ---------------------------------------------------------------------------
# T1: Empty log directory
# ---------------------------------------------------------------------------


def test_empty_logs_dir_returns_empty_page(tmp_path: Path) -> None:
    page = JsonlAuditLogReader(tmp_path / "logs").read(_query(limit=10))
    assert page.events == ()
    assert page.corrupt_count == 0
    assert page.files_scanned == 0
    assert not page.has_more


# ---------------------------------------------------------------------------
# T2: One file, fewer events than limit
# ---------------------------------------------------------------------------


def test_one_file_fewer_than_limit(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-20", [_event_line(f"c-{i}", i) for i in range(3)])
    page = JsonlAuditLogReader(logs).read(_query(limit=10))
    assert len(page.events) == 3
    assert not page.has_more
    assert page.files_scanned == 1


# ---------------------------------------------------------------------------
# T3: One file, 10 events, limit 5 → 5 NEWEST
# ---------------------------------------------------------------------------


def test_one_file_ten_events_limit_five_returns_newest(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-20", [_event_line(f"c-{i}", i * 10) for i in range(10)])
    page = JsonlAuditLogReader(logs).read(_query(limit=5))
    assert len(page.events) == 5
    corr_ids = [str(e.correlation_id) for e in page.events]
    assert corr_ids == ["c-9", "c-8", "c-7", "c-6", "c-5"]


# ---------------------------------------------------------------------------
# T4: Same timestamp → stable reverse-file-order
# ---------------------------------------------------------------------------


def test_same_timestamp_ordering_stable(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    same_ts = _BASE_TS.isoformat()
    lines = [
        _event_line("c-z", created_at=same_ts),
        _event_line("c-a", created_at=same_ts),
        _event_line("c-m", created_at=same_ts),
    ]
    _write(logs, "2026-06-20", lines)
    page = JsonlAuditLogReader(logs).read(_query(limit=3))
    assert len(page.events) == 3
    assert [str(e.correlation_id) for e in page.events] == ["c-m", "c-a", "c-z"]


# ---------------------------------------------------------------------------
# T5: Multiple daily files → global newest-first
# ---------------------------------------------------------------------------


def test_multiple_files_global_newest_first(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-18", [_event_line("old", 0)])
    _write(logs, "2026-06-19", [_event_line("mid", 86400)])
    _write(logs, "2026-06-20", [_event_line("new", 172800)])
    page = JsonlAuditLogReader(logs).read(_query(limit=10))
    assert [str(e.correlation_id) for e in page.events] == ["new", "mid", "old"]


# ---------------------------------------------------------------------------
# T7: has_more=True when limit+1 matching events found
# ---------------------------------------------------------------------------


def test_has_more_true_when_sixth_event_found(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-20", [_event_line(f"c-{i}", i) for i in range(6)])
    page = JsonlAuditLogReader(logs).read(_query(limit=5))
    assert len(page.events) == 5
    assert page.has_more is True


# ---------------------------------------------------------------------------
# T8: has_more=False when exactly limit events exist
# ---------------------------------------------------------------------------


def test_has_more_false_when_exactly_five(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-20", [_event_line(f"c-{i}", i) for i in range(5)])
    page = JsonlAuditLogReader(logs).read(_query(limit=5))
    assert len(page.events) == 5
    assert page.has_more is False


# ---------------------------------------------------------------------------
# T15: Buffer bounded at limit+1 (O(limit) memory)
# ---------------------------------------------------------------------------


def test_buffer_bounded_at_limit_plus_one(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-20", [_event_line(f"c-{i}", i) for i in range(20)])
    page = JsonlAuditLogReader(logs).read(_query(limit=5))
    assert len(page.events) == 5
    assert page.has_more is True
    assert [str(e.correlation_id) for e in page.events] == ["c-19", "c-18", "c-17", "c-16", "c-15"]
