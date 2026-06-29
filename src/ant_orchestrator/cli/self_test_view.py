"""Self-test report model + rendering (Phase 8 CP6).

Reuses the doctor :class:`CheckResult` shape (check_id/status/message/remediation)
and adds the report envelope. Human output prints one ``STATUS check.id`` line per
check; JSON output is a single ANSI-free document with a stable schema. Neither path
prints secrets, absolute paths (unless an explicit keep-workspace debug flag was set)
or raw tracebacks.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    CheckResult,
    overall_status,
)
from ant_orchestrator.cli.json_contract import JsonObject
from ant_orchestrator.config.constants import ANT_CLI_VERSION

SELF_TEST_JSON_SCHEMA_VERSION = 1
_COMMAND = "self-test"


@dataclass(frozen=True, slots=True)
class SelfTestReport:
    """The outcome of one self-test run."""

    checks: tuple[CheckResult, ...]
    duration_ms: int
    workspace_cleaned: bool
    kept_workspace_path: str | None = field(default=None)

    @property
    def overall(self) -> str:
        return overall_status(list(self.checks))

    @property
    def has_failure(self) -> bool:
        return any(c.status == STATUS_FAIL for c in self.checks)


def render_human(report: SelfTestReport) -> list[str]:
    """Render the human-facing report (no ANSI, no secrets, no absolute paths)."""
    lines = [f"Ant-Orchestrator Self-Test {ANT_CLI_VERSION}", ""]
    for check in report.checks:
        lines.append(f"{check.status} {check.check_id}: {check.message}")
        if check.remediation and check.status != STATUS_PASS:
            lines.append(f"    > {check.remediation}")
    lines.append("")
    lines.append(f"Overall: {report.overall}")
    if report.kept_workspace_path is not None:
        lines.append(f"Workspace kept at: {report.kept_workspace_path}")
    return lines


def render_json(report: SelfTestReport) -> JsonObject:
    """Render the stable JSON document for ``--json`` output."""
    return {
        "schema_version": SELF_TEST_JSON_SCHEMA_VERSION,
        "command": _COMMAND,
        "version": ANT_CLI_VERSION,
        "overall_status": report.overall,
        "checks": [
            {
                "check_id": c.check_id,
                "status": c.status,
                "message": c.message,
                "remediation": c.remediation,
            }
            for c in report.checks
        ],
        "duration_ms": report.duration_ms,
        "workspace_cleaned": report.workspace_cleaned,
    }
