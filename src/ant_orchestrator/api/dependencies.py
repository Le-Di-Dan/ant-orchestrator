"""API-edge composition — injects concrete adapters into the neutral composition root.

This module is the API equivalent of ``cli/workflow_composition.py``:
- It is the ONLY module in ``api/`` allowed to import concrete adapters.
- It must NOT be imported by ``cli/``.
- ``composition.py`` (neutral root) must NOT import from this module.
"""

from __future__ import annotations

from pathlib import Path

from ant_orchestrator.adapters.jsonl_audit_log_reader import JsonlAuditLogReader
from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.composition import SystemClock, WorkflowServices, build_workflow_services
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME


def build_api_services(workspace: Path) -> WorkflowServices:
    """Build workflow services with real audit sink and reader for the API edge."""
    logs_dir = workspace / ANT_DIRNAME / "logs"
    clock = SystemClock()
    sink = JsonlAuditSink(logs_dir, clock=clock, redactor=Redactor())
    reader = JsonlAuditLogReader(logs_dir)
    return build_workflow_services(
        workspace,
        audit_sink=sink,
        audit_log_reader=reader,
    )
