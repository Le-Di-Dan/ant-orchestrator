"""Thin CLI shim — Phase 4 CLI commands import from here for backward compat.

All assembly logic lives in :mod:`ant_orchestrator.composition` (neutral root).
This module wires the concrete ``JsonlAuditSink`` adapter (allowed only from CLI/adapters
layers) and re-exports the public names so existing CLI code requires no change.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.documentation_execution import (
    DocumentationExecutionPort,
    WorkflowDocumentationPreparer,
)
from ant_orchestrator.cli.composition import SystemClock
from ant_orchestrator.composition import (  # noqa: F401
    WorkflowServices as WorkflowServices,
)
from ant_orchestrator.composition import build_workflow_services as _build
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME


def build_workflow_services(
    start: Path,
    *,
    documentation_execution: DocumentationExecutionPort | None = None,
    documentation_preparer: WorkflowDocumentationPreparer | None = None,
) -> WorkflowServices:
    """Build workflow services with a real ``JsonlAuditSink`` for audit persistence."""
    from ant_orchestrator.workspace.discovery import find_nest

    root = find_nest(start)
    logs_dir = (root / ANT_DIRNAME / "logs") if root else (start / ANT_DIRNAME / "logs")
    clock = SystemClock()
    sink = JsonlAuditSink(logs_dir, clock=clock, redactor=Redactor())
    reader = JsonlAuditLogReader(logs_dir)
    return _build(
        start,
        documentation_execution=documentation_execution,
        documentation_preparer=documentation_preparer,
        audit_sink=sink,
        audit_log_reader=reader,
    )
