"""JsonlAuditLogReader — filtering, since, errors, filename rules (T6, T9-T14)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.application.ports.audit import AUDIT_SCHEMA_VERSION
from ant_orchestrator.application.ports.audit_log_reader import AuditLogQuery
from ant_orchestrator.application.ports.database import StorageIntegrityError

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


def _event_line(
    correlation_id: str = "corr-1",
    offset_seconds: int = 0,
    task_id: str | None = None,
) -> str:
    ts = (_BASE_TS + timedelta(seconds=offset_seconds)).isoformat()
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
# T6: Sparse task filter scans past unrelated events
# ---------------------------------------------------------------------------


def test_sparse_task_filter_scans_all_unrelated(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line(f"other-{i}", i * 10) for i in range(9)]
    lines.append(_event_line("target", 5, task_id="TASK-1"))
    _write(logs, "2026-06-20", lines)
    page = JsonlAuditLogReader(logs).read(_query(limit=5, task_id="TASK-1"))
    assert len(page.events) == 1
    assert str(page.events[0].correlation_id) == "target"


# ---------------------------------------------------------------------------
# T9: since inclusive UTC
# ---------------------------------------------------------------------------


def test_since_inclusive_filters_older_events(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    cutoff = _BASE_TS + timedelta(seconds=50)
    lines = [
        _event_line("before", 30),
        _event_line("at-cutoff", 50),
        _event_line("after", 100),
    ]
    _write(logs, "2026-06-20", lines)
    page = JsonlAuditLogReader(logs).read(_query(limit=10, since=cutoff))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "at-cutoff" in corr_ids
    assert "after" in corr_ids
    assert "before" not in corr_ids


# ---------------------------------------------------------------------------
# T10: Old files outside since not scanned
# ---------------------------------------------------------------------------


def test_old_file_outside_since_not_scanned(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    _write(logs, "2026-06-18", [_event_line("old-file", 0)])
    _write(logs, "2026-06-20", [_event_line("new-file", 0)])
    since = datetime(2026, 6, 19, 0, 0, 0, tzinfo=UTC)
    page = JsonlAuditLogReader(logs).read(_query(limit=10, since=since))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "old-file" not in corr_ids
    assert page.files_scanned == 1


# ---------------------------------------------------------------------------
# T11: Corrupt middle line → skip + corrupt_count
# ---------------------------------------------------------------------------


def test_corrupt_middle_line_skipped(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    lines = [_event_line("before"), "NOT VALID JSON {{{", _event_line("after")]
    _write(logs, "2026-06-20", lines)
    page = JsonlAuditLogReader(logs).read(_query(limit=10))
    assert page.corrupt_count == 1
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "before" in corr_ids
    assert "after" in corr_ids


# ---------------------------------------------------------------------------
# T12: Truncated final line
# ---------------------------------------------------------------------------


def test_truncated_final_line_skipped(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / "audit-2026-06-20.jsonl"
    truncated = '{"schema_version": 1, "event_type": "path_decision"'
    path.write_text(_event_line("good") + "\n" + truncated, encoding="utf-8")
    page = JsonlAuditLogReader(logs).read(_query(limit=10))
    assert page.corrupt_count == 1
    assert len(page.events) == 1
    assert str(page.events[0].correlation_id) == "good"


# ---------------------------------------------------------------------------
# T13: Unreadable file → StorageIntegrityError (deterministic via monkeypatch)
# ---------------------------------------------------------------------------


def test_unreadable_file_raises_storage_error(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "audit-2026-06-20.jsonl").write_text("", encoding="utf-8")

    original_read_text = Path.read_text

    def _failing_read_text(self: Path, **kwargs: object) -> str:
        if self.name.startswith("audit-"):
            raise PermissionError(f"[Errno 13] Permission denied: '{self}'")
        return original_read_text(self, **kwargs)  # type: ignore[arg-type]

    with patch.object(Path, "read_text", _failing_read_text):
        with pytest.raises(StorageIntegrityError):
            JsonlAuditLogReader(logs).read(_query(limit=5))


# ---------------------------------------------------------------------------
# T14: Nonmatching filename ignored
# ---------------------------------------------------------------------------


def test_nonmatching_filename_ignored(tmp_path: Path) -> None:
    logs = tmp_path / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    _write(logs, "2026-06-20", [_event_line("real")])
    # These should NOT be parsed
    (logs / "audit-2026-06-21-extra.jsonl").write_text(_event_line("fake") + "\n", encoding="utf-8")
    (logs / "2026-06-20.jsonl").write_text(_event_line("fake2") + "\n", encoding="utf-8")
    (logs / "audit-2026-06-22.txt").write_text(_event_line("fake3") + "\n", encoding="utf-8")
    page = JsonlAuditLogReader(logs).read(_query(limit=10))
    corr_ids = {str(e.correlation_id) for e in page.events}
    assert "real" in corr_ids
    assert "fake" not in corr_ids
    assert "fake2" not in corr_ids
    assert "fake3" not in corr_ids
