"""CP6 — ``ant memory search`` CLI — JSON contract, audit, ordering tests (Phase 7).

Tests 16–22: stable JSON payload shape, bounded output, deterministic ordering,
deprecated exclusion, MEMORY_RETRIEVAL audit persistence, no sensitive field leak,
immutability of memory records after search.
"""

from __future__ import annotations

import json
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.application.ports.audit import AuditEventType
from ant_orchestrator.application.ports.audit_log_reader import AuditLogQuery
from ant_orchestrator.cli.main import app
from ant_orchestrator.config.constants import LOG_DEFAULT_LIMIT, MEMORY_DEFAULT_LIMIT
from ant_orchestrator.core.domain.query import MemorySearchCriteria
from ant_orchestrator.workspace.layout import ANT_DIRNAME
from tests.support.cli_phase7_memory_helpers import (  # noqa: F401  (nest is a fixture)
    cli,
    make_record,
    nest,
    repo,
)

# --- 16. JSON full stable payload ---


def test_json_stable_payload(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-json1", tags=("t1", "t2")))
    result = cli.invoke(app, ["memory", "search", "--json", "--path", str(nest)])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == 1
    assert payload["command"] == "memory_search"
    assert "resolved_limit" in payload
    assert "returned_count" in payload
    record = payload["records"][0]
    assert "record_id" in record
    assert "type" in record
    assert "title" in record
    assert "confidence" in record
    assert "source" in record
    assert "created_at" in record
    assert "tags" in record
    assert "summary" not in record
    assert "content" not in record


# --- 17. JSON output bounded ---


def test_json_output_bounded(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    for i in range(30):
        r.append(make_record(f"m{i:03d}", offset=i))
    result = cli.invoke(app, ["memory", "search", "--limit", "5", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    assert len(payload["records"]) == 5


# --- 18. Ordering deterministic ---


def test_ordering_deterministic(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-old", offset=0))
    r.append(make_record("m-new", offset=100))
    result = cli.invoke(app, ["memory", "search", "--json", "--path", str(nest)])
    payload = json.loads(result.output)
    ids = [rec["record_id"] for rec in payload["records"]]
    assert ids == ["m-new", "m-old"]


# --- 19. Deprecated records excluded ---


def test_deprecated_excluded(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-active"))
    r.append(make_record("m-deprecated", deprecated=True))
    result = cli.invoke(app, ["memory", "search", "--path", str(nest)])
    assert result.exit_code == 0
    assert "m-active" in result.output
    assert "m-deprecated" not in result.output


# --- 20. MEMORY_RETRIEVAL audit event persisted ---


def test_memory_retrieval_audit_persisted(nest: Path) -> None:  # noqa: F811
    cli.invoke(app, ["memory", "search", "--path", str(nest)])
    logs_dir = nest / ANT_DIRNAME / "logs"
    reader = JsonlAuditLogReader(logs_dir)
    page = reader.read(AuditLogQuery(task_id=None, limit=LOG_DEFAULT_LIMIT, since=None))
    event_types = [e.event_type for e in page.events]
    assert AuditEventType.MEMORY_RETRIEVAL in event_types


# --- 21. Audit event no title/summary/content ---


def test_audit_event_no_sensitive_fields(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-audit", title="MY TITLE", summary="MY SUMMARY"))
    cli.invoke(app, ["memory", "search", "--path", str(nest)])
    logs_dir = nest / ANT_DIRNAME / "logs"
    audit_files = sorted(logs_dir.glob("audit-*.jsonl"))
    content = "".join(f.read_text("utf-8") for f in audit_files)
    assert "MY TITLE" not in content
    assert "MY SUMMARY" not in content


# --- 22. Search does not mutate memory records ---


def test_search_does_not_mutate_records(nest: Path) -> None:  # noqa: F811
    r = repo(nest)
    r.append(make_record("m-immutable", title="Original"))
    cli.invoke(app, ["memory", "search", "--path", str(nest)])
    records = r.search(MemorySearchCriteria(limit=MEMORY_DEFAULT_LIMIT))
    assert len(records) == 1
    assert records[0].title == "Original"
