"""CP0 JSONL audit sink tests: serialization, redaction-before-persist, layout.

Secret fixtures are obviously fake values, never real credentials. Tests use a
temporary directory so no ``.ant/logs`` artifact is left in the working tree.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.audit import (
    AUDIT_SCHEMA_VERSION,
    AuditEvent,
    AuditEventType,
    CorrelationId,
    PolicyDecision,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.security.redaction.redactor import Redactor

TS = UtcTimestamp(datetime(2026, 6, 22, tzinfo=UTC))
FAKE_OPENAI = "sk-" + "C" * 40
FAKE_PEM = "-----BEGIN PRIVATE KEY-----\nMIIfakeKEYmaterialNOTreal0001\n-----END PRIVATE KEY-----"


class _FixedClock:
    def now(self) -> UtcTimestamp:
        return TS


def _sink(tmp_path: Path) -> JsonlAuditSink:
    return JsonlAuditSink(tmp_path / ".ant" / "logs", clock=_FixedClock(), redactor=Redactor())


def _event(detail: dict[str, str], *, decision: PolicyDecision | None = None) -> AuditEvent:
    return AuditEvent(
        event_type=AuditEventType.EXECUTION,
        correlation_id=CorrelationId("corr-1"),
        created_at=TS,
        detail=detail,
        decision=decision,
    )


def _audit_file(tmp_path: Path) -> Path:
    return tmp_path / ".ant" / "logs" / "audit-2026-06-22.jsonl"


def test_creates_logs_dir_and_deterministic_filename(tmp_path: Path) -> None:
    _sink(tmp_path).write(_event({"op": "run"}))
    assert _audit_file(tmp_path).is_file()


def test_writes_one_json_object_per_line(tmp_path: Path) -> None:
    sink = _sink(tmp_path)
    sink.write(_event({"op": "a"}))
    sink.write(_event({"op": "b"}))
    lines = _audit_file(tmp_path).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert [json.loads(line)["detail"]["op"] for line in lines] == ["a", "b"]


def test_serialized_event_has_schema_and_stable_enum_values(tmp_path: Path) -> None:
    _sink(tmp_path).write(_event({"op": "run"}, decision=PolicyDecision.ALLOW))
    record = json.loads(_audit_file(tmp_path).read_text(encoding="utf-8").splitlines()[0])
    assert record["schema_version"] == AUDIT_SCHEMA_VERSION
    assert record["event_type"] == "execution"
    assert record["decision"] == "allow"
    assert record["correlation_id"] == "corr-1"
    assert record["created_at"] == TS.to_iso()


def test_secret_in_detail_is_redacted_before_persist(tmp_path: Path) -> None:
    _sink(tmp_path).write(_event({"stdout": f"using {FAKE_OPENAI} now"}))
    content = _audit_file(tmp_path).read_text(encoding="utf-8")
    assert FAKE_OPENAI not in content
    assert "sk-" not in content
    assert "[REDACTED]" in content


def test_private_key_never_reaches_disk(tmp_path: Path) -> None:
    _sink(tmp_path).write(_event({"stderr": FAKE_PEM}))
    content = _audit_file(tmp_path).read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in content
    assert "fakeKEYmaterial" not in content


def test_each_line_is_valid_json(tmp_path: Path) -> None:
    sink = _sink(tmp_path)
    for index in range(3):
        sink.write(_event({"op": str(index)}))
    for line in _audit_file(tmp_path).read_text(encoding="utf-8").splitlines():
        assert isinstance(json.loads(line), dict)
