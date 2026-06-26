"""Stable ``--json`` payloads for the Phase 4 CLI commands (PHASE_4_PLAN CP7 §11).

Every payload carries ``schema_version`` (a single constant) and uses stable field
names with enum values serialized as strings and absent optionals as ``null``. Error
payloads share one shape (``error.type`` / ``error.message``) and never expose a raw
exception, stack trace, checkpoint channel or request payload.
"""

from __future__ import annotations

import json
from typing import Any

from ant_orchestrator.application.services.task_status import TaskStatusReport
from ant_orchestrator.application.services.workflow_support import WorkflowOutcome
from ant_orchestrator.config.constants import CLI_JSON_SCHEMA_VERSION
from ant_orchestrator.core.domain.entities import Task

JsonObject = dict[str, Any]


def _base(command: str) -> JsonObject:
    """Start a payload with the version stamp and command name."""
    return {"schema_version": CLI_JSON_SCHEMA_VERSION, "command": command}


def dumps(payload: JsonObject) -> str:
    """Render a payload as the single JSON document printed to stdout."""
    return json.dumps(payload)


def create_payload(task: Task) -> JsonObject:
    """Payload for ``ant task create``."""
    payload = _base("task_create")
    payload["task_id"] = task.id.value
    payload["status"] = task.status.value
    payload["priority"] = task.priority.value
    return payload


def outcome_payload(command: str, task_id: str, outcome: WorkflowOutcome) -> JsonObject:
    """Payload for run/approve/reject/cancel (a :class:`WorkflowOutcome`)."""
    payload = _base(command)
    payload["task_id"] = task_id
    payload["workflow_run_id"] = outcome.run_id or None
    payload["status"] = outcome.status
    payload["pending_approval"] = (
        {"approval_id": outcome.approval_id} if outcome.approval_id is not None else None
    )
    return payload


def status_payload(report: TaskStatusReport, *, workspace_ready: bool) -> JsonObject:
    """Payload for ``ant status``."""
    payload = _base("status")
    payload["workspace"] = {"ready": workspace_ready}
    payload["total"] = report.total
    payload["truncated"] = report.truncated
    payload["tasks"] = [
        {
            "task_id": row.task_id,
            "status": row.status,
            "priority": row.priority,
            "workflow_run_id": row.workflow_run_id,
            "run_status": row.run_status,
            "pending_gate_type": row.pending_gate_type,
            "cancel_requested": row.cancel_requested,
        }
        for row in report.rows
    ]
    return payload


def error_payload(command: str, error: BaseException) -> JsonObject:
    """Sanitized error payload: type name + message only (no traceback)."""
    payload = _base(command)
    payload["error"] = {"type": type(error).__name__, "message": str(error)}
    return payload
