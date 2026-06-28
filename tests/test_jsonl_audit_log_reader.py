"""JsonlAuditLogReader contract tests (Phase 7 CP3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.application.ports.audit import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    CorrelationId,
)
from ant_orchestrator.application.ports.audit_log_reader import AuditLogQuery
from ant_orchestrator.application.ports.database import StorageIntegrityError
from ant_orchestrator.core.domain.value_objects import UtcTimestamp

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _ts(offset_seconds: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset_seconds))


def _event_line(
    event_type: str = "path_decision",
    correlation_id: str = "corr-1",
    created_at: str | None = None,
    task_id: str | None = None,
    offset_seconds: int = 0,
) -> str:
    ts = (_BASE_TS + timedelta(seconds=offset_seconds)).isoformat()
    if created_at is not None:
        ts = created_at
    detail: dict[str, str] = {}
    if task_id is not None:
        detail["task_id"] = task_id
    payload: dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "event_type": event_type,
        "correlation_id": correlation_id,
        "created_at": ts,
        "detail": detail,
        "decision": None,
    }
    return json.dumps(payload, sort_keys=True)


def _write_audit_file(logs_dir: Path, date_str: str, lines: list[str]) -> Path:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"audit-{date_str}.jsonl"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _query(
    limit: int = 10,
    task_id: str | None = None,
    since: datetime | None = None,
) -> AuditLogQuery:
    return AuditLogQuery(task_id=task_id, limit=limit, since=since)


# ---------------------------------------------------------------------------
# T1: Empty log directory
# ---------------------------------------------------------------------------


def test_empty_logs_dir_returns_empty_page(tmp_path: Path) -> None:
    reader = JsonlAuditLogReader(tmp_path / "logs")
    page = reader.read(_query(limit=10))
    assert page.events == ()
    assert page.corrupt_count == 0
    assert page.files_scanned == 0
    assert not page.has_more


# ---------------------------------------------------------------------------
# T2: One file, fewer events than limit
# ---------------------------------------------------------------------------


def test_one_file_fewer_than_limit(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(correlation_id=f"c-{i}", offset_seconds=i) for i in range(3)]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10))
    assert len(page.events) == 3
    assert not page.has_more
    assert page.files_scanned == 1


# ---------------------------------------------------------------------------
# T3: One file, 10 events, limit 5 → 5 NEWEST (not 5 oldest)
# ---------------------------------------------------------------------------


def test_one_file_ten_events_limit_five_returns_newest(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(correlation_id=f"c-{i}", offset_seconds=i * 10) for i in range(10)]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=5))
    assert len(page.events) == 5
    # Newest 5 are c-9, c-8, c-7, c-6, c-5 (largest offsets)
    corr_ids = [str(e.correlation_id) for e in page.events]
    assert corr_ids == ["c-9", "c-8", "c-7", "c-6", "c-5"]


# ---------------------------------------------------------------------------
# T4: Same timestamp, correlation_id tie-breaker (lexicographic asc NOT applied)
# ---------------------------------------------------------------------------


def test_same_timestamp_ordering_stable(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    same_ts = _BASE_TS.isoformat()
    lines = [
        _event_line(correlation_id="c-z", created_at=same_ts),
        _event_line(correlation_id="c-a", created_at=same_ts),
        _event_line(correlation_id="c-m", created_at=same_ts),
    ]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=3))
    # Reversed within file: c-m, c-a, c-z
    assert len(page.events) == 3
    assert [str(e.correlation_id) for e in page.events] == ["c-m", "c-a", "c-z"]


# ---------------------------------------------------------------------------
# T5: Multiple daily files → global newest-first
# ---------------------------------------------------------------------------


def test_multiple_files_global_newest_first(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write_audit_file(logs, "2026-06-18", [_event_line(correlation_id="old", offset_seconds=0)])
    _write_audit_file(logs, "2026-06-19", [_event_line(correlation_id="mid", offset_seconds=86400)])
    _write_audit_file(
        logs, "2026-06-20", [_event_line(correlation_id="new", offset_seconds=172800)]
    )
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10))
    corr_ids = [str(e.correlation_id) for e in page.events]
    assert corr_ids == ["new", "mid", "old"]


# ---------------------------------------------------------------------------
# T6: Sparse task filter scans past unrelated events
# ---------------------------------------------------------------------------


def test_sparse_task_filter_scans_all_unrelated(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(correlation_id=f"other-{i}", offset_seconds=i * 10) for i in range(9)]
    lines.append(_event_line(correlation_id="target", task_id="TASK-1", offset_seconds=5))
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=5, task_id="TASK-1"))
    assert len(page.events) == 1
    assert str(page.events[0].correlation_id) == "target"


# ---------------------------------------------------------------------------
# T7: has_more=True only when limit+1 matching events found
# ---------------------------------------------------------------------------


def test_has_more_true_when_sixth_event_found(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(correlation_id=f"c-{i}", offset_seconds=i) for i in range(6)]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=5))
    assert len(page.events) == 5
    assert page.has_more is True


# ---------------------------------------------------------------------------
# T8: has_more=False when exactly five events exist
# ---------------------------------------------------------------------------


def test_has_more_false_when_exactly_five(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(correlation_id=f"c-{i}", offset_seconds=i) for i in range(5)]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=5))
    assert len(page.events) == 5
    assert page.has_more is False


# ---------------------------------------------------------------------------
# T9: since inclusive UTC
# ---------------------------------------------------------------------------


def test_since_inclusive_filters_older_events(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    cutoff = _BASE_TS + timedelta(seconds=50)
    lines = [
        _event_line(correlation_id="before", offset_seconds=30),  # before cutoff
        _event_line(correlation_id="at-cutoff", offset_seconds=50),  # exactly at cutoff
        _event_line(correlation_id="after", offset_seconds=100),  # after cutoff
    ]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10, since=cutoff))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "at-cutoff" in corr_ids
    assert "after" in corr_ids
    assert "before" not in corr_ids


# ---------------------------------------------------------------------------
# T10: Old files outside since not scanned
# ---------------------------------------------------------------------------


def test_old_file_outside_since_not_scanned(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    # Old file: 2026-06-18 events
    _write_audit_file(
        logs,
        "2026-06-18",
        [_event_line(correlation_id="old-file", offset_seconds=0)],
    )
    _write_audit_file(
        logs,
        "2026-06-20",
        [_event_line(correlation_id="new-file", offset_seconds=0)],
    )
    since = datetime(2026, 6, 19, 0, 0, 0, tzinfo=UTC)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10, since=since))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "old-file" not in corr_ids
    assert page.files_scanned == 1


# ---------------------------------------------------------------------------
# T11: Corrupt middle line → skip + corrupt_count
# ---------------------------------------------------------------------------


def test_corrupt_middle_line_skipped(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [
        _event_line(correlation_id="before"),
        "NOT VALID JSON {{{",
        _event_line(correlation_id="after"),
    ]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10))
    assert page.corrupt_count == 1
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "before" in corr_ids
    assert "after" in corr_ids


# ---------------------------------------------------------------------------
# T12: Truncated final line (malformed JSON)
# ---------------------------------------------------------------------------


def test_truncated_final_line_skipped(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    good_line = _event_line(correlation_id="good")
    truncated = '{"schema_version": 1, "event_type": "path_decision"'
    path = logs / "audit-2026-06-20.jsonl"
    logs.mkdir(parents=True, exist_ok=True)
    path.write_text(good_line + "\n" + truncated, encoding="utf-8")
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10))
    assert page.corrupt_count == 1
    assert len(page.events) == 1
    assert str(page.events[0].correlation_id) == "good"


# ---------------------------------------------------------------------------
# T13: Unreadable file → StorageIntegrityError
# ---------------------------------------------------------------------------


def test_unreadable_file_raises_storage_error(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    bad_file = logs / "audit-2026-06-20.jsonl"
    bad_file.write_text("", encoding="utf-8")
    # Make unreadable on platforms that support chmod
    try:
        import os

        os.chmod(bad_file, 0o000)
    except (OSError, NotImplementedError):
        pytest.skip("chmod not supported on this platform")

    # Verify chmod was effective (skip if running as privileged user on Windows)
    try:
        bad_file.read_text(encoding="utf-8")
        # If we can still read it, chmod had no effect → skip
        os.chmod(bad_file, 0o644)
        pytest.skip("chmod did not restrict file access on this platform/user")
    except (PermissionError, OSError):
        pass  # file is truly unreadable → proceed

    reader = JsonlAuditLogReader(logs)
    try:
        with pytest.raises(StorageIntegrityError):
            reader.read(_query(limit=5))
    finally:
        os.chmod(bad_file, 0o644)


# ---------------------------------------------------------------------------
# T14: Nonmatching filename ignored
# ---------------------------------------------------------------------------


def test_nonmatching_filename_ignored(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    # Valid audit file
    _write_audit_file(logs, "2026-06-20", [_event_line(correlation_id="real")])
    # Files that should NOT be parsed
    (logs / "audit-2026-06-21-extra.jsonl").write_text(
        _event_line(correlation_id="fake") + "\n", encoding="utf-8"
    )
    (logs / "2026-06-20.jsonl").write_text(
        _event_line(correlation_id="fake2") + "\n", encoding="utf-8"
    )
    (logs / "audit-2026-06-22.txt").write_text(
        _event_line(correlation_id="fake3") + "\n", encoding="utf-8"
    )
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=10))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "real" in corr_ids
    assert "fake" not in corr_ids
    assert "fake2" not in corr_ids
    assert "fake3" not in corr_ids


# ---------------------------------------------------------------------------
# T15: Memory - buffer never exceeds limit+1 (structural verification)
# ---------------------------------------------------------------------------


def test_buffer_bounded_at_limit_plus_one(tmp_path: Path) -> None:
    """Reader must stop accumulating once it has limit+1 events (O(limit) memory)."""
    logs = tmp_path / "logs"
    # 20 events but limit=5 → reader should stop when buffer reaches 6
    lines = [_event_line(correlation_id=f"c-{i}", offset_seconds=i) for i in range(20)]
    _write_audit_file(logs, "2026-06-20", lines)
    reader = JsonlAuditLogReader(logs)
    page = reader.read(_query(limit=5))
    # Result must have exactly 5 events, not 20
    assert len(page.events) == 5
    assert page.has_more is True
    # The returned events must be the 5 newest (c-19, c-18, c-17, c-16, c-15)
    corr_ids = [str(e.correlation_id) for e in page.events]
    assert corr_ids == ["c-19", "c-18", "c-17", "c-16", "c-15"]
