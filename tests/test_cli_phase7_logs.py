"""CP6 — ``ant logs`` CLI command tests (Phase 7).

Uses a real temporary workspace + composition; seeds JSONL audit events directly
via ``JsonlAuditSink``; invokes CLI via Typer CliRunner.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.audit import AuditEvent, AuditEventType, CorrelationId
from ant_orchestrator.cli.main import app
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME

cli = CliRunner()

_BASE_TS = datetime(2026, 6, 20, 12, 0, 0, tzinfo=UTC)


class _FixedClock:
    def __init__(self, ts: datetime) -> None:
        self._ts = ts

    def now(self) -> UtcTimestamp:
        return UtcTimestamp(self._ts)


def _ts(offset: int = 0) -> UtcTimestamp:
    return UtcTimestamp(_BASE_TS + timedelta(seconds=offset))


def _seed_event(
    sink: JsonlAuditSink,
    *,
    corr: str = "corr-001",
    event_type: AuditEventType = AuditEventType.ROUTING_DECISION,
    ts: UtcTimestamp | None = None,
    task_id: str | None = None,
) -> AuditEvent:
    detail: dict[str, str] = {}
    if task_id:
        detail["task_id"] = task_id
    event = AuditEvent(
        event_type=event_type,
        correlation_id=CorrelationId(corr),
        created_at=ts or _ts(),
        detail=detail,
    )
    sink.write(event)
    return event


def _make_sink(root: Path) -> JsonlAuditSink:
    logs_dir = root / ANT_DIRNAME / "logs"
    return JsonlAuditSink(logs_dir, clock=_FixedClock(_BASE_TS), redactor=Redactor())


@pytest.fixture
def nest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    result = cli.invoke(app, ["init"])
    assert result.exit_code == 0
    return tmp_path


# --- 1. Command is in root help ---


def test_logs_in_root_help(nest: Path) -> None:
    result = cli.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "logs" in result.output


# --- 2. Empty logs → exit 0 ---


def test_empty_logs_exits_zero(nest: Path) -> None:
    result = cli.invoke(app, ["logs", "--path", str(nest)])
    assert result.exit_code == 0


# --- 3. Human output newest-first ---


def test_human_output_newest_first(nest: Path) -> None:
    sink = _make_sink(nest)
    _seed_event(sink, corr="c1", ts=_ts(0))
    _seed_event(sink, corr="c2", ts=_ts(10))
    result = cli.invoke(app, ["logs", "--path", str(nest)])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 2
    # newest (c2) comes first
    assert "c2" in lines[0][:40] or lines[0] > lines[1]


# --- 4. --limit 5 from more than 5 events → exactly 5 ---


def test_limit_five_from_ten(nest: Path) -> None:
    sink = _make_sink(nest)
    for i in range(10):
        _seed_event(sink, corr=f"c{i:02d}", ts=_ts(i))
    result = cli.invoke(app, ["logs", "--limit", "5", "--path", str(nest)])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) == 5


# --- 5. --task filter ---


def test_task_filter(nest: Path) -> None:
    sink = _make_sink(nest)
    _seed_event(sink, corr="c-task", task_id="TASK-1", ts=_ts(0))
    _seed_event(sink, corr="c-other", ts=_ts(1))
    result = cli.invoke(app, ["logs", "--task", "TASK-1", "--path", str(nest)])
    assert result.exit_code == 0
    assert "c-task"[:8] in result.output
    assert "c-other"[:8] not in result.output


# --- 6. --since inclusive ---


def test_since_inclusive(nest: Path) -> None:
    sink = _make_sink(nest)
    old_ts = _ts(-100)
    new_ts = _ts(0)
    _seed_event(sink, corr="c-old", ts=old_ts)
    _seed_event(sink, corr="c-new", ts=new_ts)
    since_str = new_ts.to_iso()
    result = cli.invoke(app, ["logs", "--since", since_str, "--path", str(nest)])
    assert result.exit_code == 0
    assert "c-new"[:8] in result.output
    assert "c-old"[:8] not in result.output


# --- 7. --json full stable payload ---


def test_json_payload_shape(nest: Path) -> None:
    sink = _make_sink(nest)
    _seed_event(sink, corr="cx1", task_id="T1", ts=_ts(0))
    result = cli.invoke(app, ["logs", "--json", "--path", str(nest)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["command"] == "logs"
    assert "limit" in payload
    assert "has_more" in payload
    assert "corrupt_count" in payload
    assert "files_scanned" in payload
    assert isinstance(payload["entries"], list)
    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["event_type"] == "routing_decision"
    assert entry["task_id"] == "T1"


# --- 8. JSON has_more / corrupt_count / files_scanned ---


def test_json_has_more_true(nest: Path) -> None:
    sink = _make_sink(nest)
    for i in range(6):
        _seed_event(sink, corr=f"c{i:02d}", ts=_ts(i))
    result = cli.invoke(app, ["logs", "--limit", "5", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert payload["has_more"] is True
    assert len(payload["entries"]) == 5


def test_json_has_more_false_when_all_scanned(nest: Path) -> None:
    sink = _make_sink(nest)
    for i in range(3):
        _seed_event(sink, corr=f"c{i}", ts=_ts(i))
    result = cli.invoke(app, ["logs", "--limit", "5", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert payload["has_more"] is False


def test_json_files_scanned(nest: Path) -> None:
    sink = _make_sink(nest)
    _seed_event(sink, corr="csc", ts=_ts(0))
    result = cli.invoke(app, ["logs", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert payload["files_scanned"] == 1


# --- 9–11. Invalid limit ---


def test_explicit_limit_zero_exits_usage(nest: Path) -> None:
    result = cli.invoke(app, ["logs", "--limit", "0", "--path", str(nest)])
    assert result.exit_code == 2


def test_negative_limit_exits_usage(nest: Path) -> None:
    result = cli.invoke(app, ["logs", "--limit", "-1", "--path", str(nest)])
    assert result.exit_code == 2


def test_over_max_limit_exits_usage(nest: Path) -> None:
    result = cli.invoke(app, ["logs", "--limit", "999", "--path", str(nest)])
    assert result.exit_code == 2


# --- 12. Invalid --since timestamp ---


def test_invalid_since_exits_usage(nest: Path) -> None:
    result = cli.invoke(app, ["logs", "--since", "not-a-date", "--path", str(nest)])
    assert result.exit_code == 2


# --- 13. Corrupt JSONL line → command succeeds, corrupt_count correct ---


def test_corrupt_line_skipped_command_succeeds(nest: Path) -> None:
    sink = _make_sink(nest)
    _seed_event(sink, corr="good1", ts=_ts(0))
    logs_dir = nest / ANT_DIRNAME / "logs"
    audit_file = sorted(logs_dir.glob("audit-*.jsonl"))[0]
    with audit_file.open("a", encoding="utf-8") as fh:
        fh.write("{not valid json\n")
    result = cli.invoke(app, ["logs", "--json", "--path", str(nest)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["corrupt_count"] == 1
    assert len(payload["entries"]) == 1


# --- 14. Unreadable file → infrastructure failure, no traceback ---


def test_unreadable_file_infrastructure_exit(nest: Path) -> None:
    import os
    import sys

    sink = _make_sink(nest)
    _seed_event(sink, corr="blocked", ts=_ts(0))
    logs_dir = nest / ANT_DIRNAME / "logs"
    audit_file = sorted(logs_dir.glob("audit-*.jsonl"))[0]
    if sys.platform != "win32":
        os.chmod(str(audit_file), 0o000)
        result = cli.invoke(app, ["logs", "--path", str(nest)])
        os.chmod(str(audit_file), 0o644)
        assert result.exit_code == 4
        assert "Traceback" not in result.output


# --- 15. Output bounded ---


def test_output_bounded(nest: Path) -> None:
    sink = _make_sink(nest)
    for i in range(20):
        _seed_event(sink, corr=f"c{i:02d}", ts=_ts(i))
    result = cli.invoke(app, ["logs", "--limit", "5", "--path", str(nest)])
    assert result.exit_code == 0
    lines = [ln for ln in result.output.splitlines() if ln.strip()]
    assert len(lines) <= 5


# --- 16. Read-only: no state mutation ---


def test_logs_does_not_mutate_workflow_state(nest: Path) -> None:
    from ant_orchestrator.cli.workflow_composition import build_workflow_services

    services = build_workflow_services(nest)
    report_before = services.task_status.report()
    sink = _make_sink(nest)
    _seed_event(sink, corr="readonly-test", ts=_ts(0))
    cli.invoke(app, ["logs", "--path", str(nest)])
    report_after = services.task_status.report()
    assert report_before.total == report_after.total
