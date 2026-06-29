"""Self-test check builders (Phase 8 CP6).

Each function performs a *real* observation against the deterministic, isolated
self-test environment and returns one or more :class:`CheckResult` rows with a
stable ``check_id``. No function fabricates a check that always passes; every row
reflects an actual probe (connect, query, write/read, file scan).
"""

from __future__ import annotations

import platform
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    CorrelationId,
)
from ant_orchestrator.application.ports.audit_log_reader import AuditLogQuery
from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    CheckResult,
)
from ant_orchestrator.config.constants import ANT_CLI_VERSION, EXPECTED_DB_SCHEMA_VERSION
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseInspector

# A synthetic provider-token-shaped value used only to prove audit redaction works.
# It is NOT a real secret; the check asserts it never reaches disk in the clear.
_REDACTION_PROBE = "sk-selftestAAAAAAAAAAAAAAAAAAAA"


def runtime_checks() -> list[CheckResult]:
    """Installation/runtime facts — never fail a source checkout for being unfrozen."""
    frozen = getattr(sys, "frozen", False)
    return [
        CheckResult("runtime.version", STATUS_PASS, ANT_CLI_VERSION),
        CheckResult("runtime.platform", STATUS_PASS, platform.system()),
        CheckResult("runtime.architecture", STATUS_PASS, platform.machine()),
        CheckResult(
            "runtime.entrypoint",
            STATUS_PASS,
            Path(sys.argv[0]).name or "antctl",
        ),
        CheckResult(
            "runtime.python_frozen_state",
            STATUS_PASS,
            "frozen native binary" if frozen else "source/interpreter mode",
        ),
    ]


def database_checks(database: Database) -> list[CheckResult]:
    """Open the state DB, verify JSON1, schema version and a clean reopen."""
    results: list[CheckResult] = []
    try:
        with database.connect() as conn:
            conn.execute("SELECT 1")
        results.append(CheckResult("database.open", STATUS_PASS, "state.sqlite opened"))
    except sqlite3.DatabaseError as exc:
        results.append(CheckResult("database.open", STATUS_FAIL, f"cannot open state DB: {exc}"))
        return results

    try:
        with database.connect() as conn:
            conn.execute("SELECT count(*) FROM json_each('[]')")
        results.append(CheckResult("database.json1", STATUS_PASS, "JSON1 extension available"))
    except sqlite3.OperationalError:
        results.append(
            CheckResult("database.json1", STATUS_FAIL, "SQLite JSON1 extension unavailable")
        )

    version = SqliteDatabaseInspector().schema_version(database.path)
    if version == EXPECTED_DB_SCHEMA_VERSION:
        results.append(CheckResult("database.schema_v5", STATUS_PASS, f"schema v{version}"))
    else:
        results.append(
            CheckResult(
                "database.schema_v5",
                STATUS_FAIL,
                f"schema v{version} (expected v{EXPECTED_DB_SCHEMA_VERSION})",
            )
        )

    reopened = SqliteDatabaseInspector().schema_version(database.path)
    results.append(
        CheckResult(
            "database.reopen",
            STATUS_PASS if reopened == version else STATUS_FAIL,
            "reopened with the same schema version",
        )
    )
    return results


def checkpoint_checks(checkpoint_db_path: Path) -> list[CheckResult]:
    """Verify the durable LangGraph checkpoint DB exists, has rows and reopens."""
    results: list[CheckResult] = []
    if not checkpoint_db_path.exists():
        results.append(
            CheckResult("checkpoint.open", STATUS_FAIL, "checkpoints.sqlite was not created")
        )
        results.append(CheckResult("checkpoint.write_read", STATUS_SKIP, "no checkpoint DB"))
        results.append(CheckResult("checkpoint.reopen", STATUS_SKIP, "no checkpoint DB"))
        return results
    results.append(CheckResult("checkpoint.open", STATUS_PASS, "checkpoints.sqlite present"))

    count = _checkpoint_row_count(checkpoint_db_path)
    results.append(
        CheckResult(
            "checkpoint.write_read",
            STATUS_PASS if count >= 1 else STATUS_FAIL,
            f"{count} checkpoint row(s) durable",
        )
    )
    reopened = _checkpoint_row_count(checkpoint_db_path)
    results.append(
        CheckResult(
            "checkpoint.reopen",
            STATUS_PASS if reopened == count else STATUS_FAIL,
            "reopened with the same checkpoint count",
        )
    )
    return results


def _checkpoint_row_count(path: Path) -> int:
    """Count rows in the LangGraph ``checkpoints`` table via a fresh connection."""
    conn = sqlite3.connect(str(path))
    try:
        names = {
            str(r[0]) for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if "checkpoints" not in names:
            return 0
        row = conn.execute("SELECT count(*) FROM checkpoints").fetchone()
        return int(row[0]) if row else 0
    finally:
        conn.close()


def audit_checks(
    sink: JsonlAuditSink,
    reader: JsonlAuditLogReader,
    logs_dir: Path,
) -> list[CheckResult]:
    """Write events through the sink, read them back, and prove redaction."""
    results: list[CheckResult] = []
    now = UtcTimestamp(datetime(2024, 1, 1, tzinfo=UTC))
    sink.write(
        AuditEvent(
            event_type=AuditEventType.EXECUTION,
            correlation_id=CorrelationId("selftest-audit"),
            created_at=now,
            detail={"phase": "self-test", "token": _REDACTION_PROBE},
        )
    )
    files = [p for p in logs_dir.glob("audit-*.jsonl") if p.is_file()]
    results.append(
        CheckResult(
            "audit.write",
            STATUS_PASS if files else STATUS_FAIL,
            "audit event persisted to JSONL" if files else "no audit file written",
        )
    )

    page = reader.read(AuditLogQuery(task_id=None, limit=10, since=None))
    results.append(
        CheckResult(
            "audit.read",
            STATUS_PASS if page.events else STATUS_FAIL,
            f"{len(page.events)} audit event(s) read back",
        )
    )

    leaked = any(_REDACTION_PROBE in p.read_text(encoding="utf-8") for p in files)
    redacted = any("[REDACTED]" in p.read_text(encoding="utf-8") for p in files)
    results.append(
        CheckResult(
            "audit.redaction",
            STATUS_PASS if (redacted and not leaked) else STATUS_FAIL,
            "secret-shaped value redacted before persistence"
            if (redacted and not leaked)
            else "redaction did not remove the secret-shaped value",
        )
    )
    return results


def security_scan_checks(
    workspace: Path,
    secret_values: tuple[str, ...],
) -> list[CheckResult]:
    """Scan every file under the workspace for known secret values and the probe."""
    needles = tuple(v for v in secret_values if v) + (_REDACTION_PROBE,)
    leaked_in: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # The probe is allowed only in its redacted form; a raw match is a leak.
        if any(n in text for n in needles):
            leaked_in.append(path.name)
    return [
        CheckResult(
            "security.no_secret",
            STATUS_PASS if not leaked_in else STATUS_FAIL,
            "no secret value found in workspace files"
            if not leaked_in
            else f"secret-shaped value leaked into {len(leaked_in)} file(s)",
        )
    ]
