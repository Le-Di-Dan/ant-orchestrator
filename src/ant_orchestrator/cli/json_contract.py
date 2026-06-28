"""Stable ``--json`` payloads for the Phase 4 CLI commands (PHASE_4_PLAN CP7 §11).

Every payload carries ``schema_version`` (a single constant) and uses stable field
names with enum values serialized as strings and absent optionals as ``null``. Error
payloads share one shape (``error.type`` / ``error.message``) and never expose a raw
exception, stack trace, checkpoint channel or request payload.
"""

from __future__ import annotations

import json
from typing import Any

from ant_orchestrator.application.ports.audit import AuditEvent
from ant_orchestrator.application.ports.audit_log_reader import AuditLogPage
from ant_orchestrator.application.services.search_memory import MemorySearchResult
from ant_orchestrator.application.services.task_status import TaskStatusReport
from ant_orchestrator.application.services.workflow_support import WorkflowOutcome
from ant_orchestrator.config.constants import CLI_JSON_SCHEMA_VERSION
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.records import MemoryRecord

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


def logs_payload(page: AuditLogPage, *, resolved_limit: int) -> JsonObject:
    """Payload for ``ant logs``."""
    payload = _base("logs")
    payload["limit"] = resolved_limit
    payload["has_more"] = page.has_more
    payload["corrupt_count"] = page.corrupt_count
    payload["files_scanned"] = page.files_scanned
    payload["entries"] = [_audit_entry(e) for e in page.events]
    return payload


def memory_search_payload(result: MemorySearchResult) -> JsonObject:
    """Payload for ``ant memory search``."""
    payload = _base("memory_search")
    payload["resolved_limit"] = result.resolved_limit
    payload["returned_count"] = result.returned_count
    payload["records"] = [_memory_record_entry(r) for r in result.records]
    return payload


def _audit_entry(event: AuditEvent) -> JsonObject:
    """Safe serialization of one AuditEvent — no raw detail dump."""
    return {
        "event_type": event.event_type.value,
        "created_at": event.created_at.to_iso(),
        "correlation_id": str(event.correlation_id),
        "task_id": event.detail.get("task_id") or None,
        "decision": event.decision.value if event.decision is not None else None,
    }


def _memory_record_entry(record: MemoryRecord) -> JsonObject:
    """Safe serialization of one MemoryRecord — no summary or raw content."""
    return {
        "record_id": record.id.value,
        "type": record.type.value,
        "title": record.title,
        "confidence": record.confidence.value if record.confidence is not None else None,
        "source": record.source,
        "created_at": record.created_at.to_iso(),
        "tags": list(record.tags),
        "task_id": record.task_id.value if record.task_id is not None else None,
    }
