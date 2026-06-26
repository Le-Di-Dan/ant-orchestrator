"""Phase 4 schema fragments: workflow-execution tables and indexes (schema v2).

These DDL fragments are composed into the full v2 schema by ``schema`` and replayed
by the v1->v2 migration. ``workflow_runs`` is defined separately because the v2
``approvals`` table FK-references it, so it must be created first.
"""

from __future__ import annotations

from ant_orchestrator.core.domain.enums import (
    ActorSource,
    ApprovalStatus,
    ExecutionAttemptStatus,
    GateType,
    ResumeOperationStatus,
    TransitionSubject,
    TransitionTrigger,
    WorkflowRunStatus,
)
from ant_orchestrator.persistence.schema_common import (
    check_in,
    check_in_members,
    members_list,
)

_RESOLVED = (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED, ApprovalStatus.CANCELLED)
_ACTIVE_RUN = (WorkflowRunStatus.RUNNING, WorkflowRunStatus.AWAITING_APPROVAL)
_ACTIVE_ATTEMPT = (ExecutionAttemptStatus.PLANNED, ExecutionAttemptStatus.STARTED)

# workflow_runs must precede approvals (approvals FK-references it).
WORKFLOW_RUNS_DDL = f"""CREATE TABLE workflow_runs (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK ({check_in("status", WorkflowRunStatus)}),
    workflow_definition_version INTEGER NOT NULL CHECK (workflow_definition_version >= 1),
    initial_invoke_operation_id TEXT NOT NULL,
    checkpoint_ever_observed INTEGER NOT NULL DEFAULT 0
        CHECK (checkpoint_ever_observed IN (0, 1)),
    last_observed_checkpoint_id TEXT,
    cancel_requested_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

# v2 approvals: v1 columns + Phase 4 gate/coordination columns (all new ones nullable).
APPROVALS_V2_DDL = f"""CREATE TABLE approvals (
    id TEXT PRIMARY KEY NOT NULL,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE RESTRICT,
    checkpoint_id TEXT REFERENCES workflow_checkpoints(id) ON DELETE RESTRICT,
    status TEXT NOT NULL CHECK ({check_in("status", ApprovalStatus)}),
    reason TEXT,
    requested_at TEXT NOT NULL,
    decided_at TEXT,
    workflow_run_id TEXT REFERENCES workflow_runs(id) ON DELETE RESTRICT,
    gate_type TEXT CHECK ({check_in("gate_type", GateType, nullable=True)}),
    gate_instance_id TEXT,
    approval_gate_sequence INTEGER
        CHECK (approval_gate_sequence IS NULL OR approval_gate_sequence >= 0),
    actor_source TEXT CHECK ({check_in("actor_source", ActorSource, nullable=True)}),
    actor_label TEXT,
    approval_row_version INTEGER NOT NULL DEFAULT 1 CHECK (approval_row_version >= 1),
    langgraph_checkpoint_id TEXT,
    langgraph_interrupt_id TEXT,
    request_json TEXT,
    CHECK (
        (status = '{ApprovalStatus.PENDING.value}' AND decided_at IS NULL)
        OR ({check_in_members("status", _RESOLVED)} AND decided_at IS NOT NULL)
    )
)"""

# Tables created after approvals (status_transitions/execution_attempts FK runs;
# resume_operations FK-references both runs and approvals).
WORKFLOW_AUX_DDL: tuple[str, ...] = (
    f"""CREATE TABLE status_transitions (
        id TEXT PRIMARY KEY NOT NULL,
        workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE RESTRICT,
        subject TEXT NOT NULL CHECK ({check_in("subject", TransitionSubject)}),
        from_status TEXT,
        to_status TEXT NOT NULL,
        trigger TEXT NOT NULL CHECK ({check_in("trigger", TransitionTrigger)}),
        operation_id TEXT NOT NULL,
        causation_id TEXT,
        created_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE execution_attempts (
        id TEXT PRIMARY KEY NOT NULL,
        workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE RESTRICT,
        logical_action_id TEXT NOT NULL,
        attempt_no INTEGER NOT NULL CHECK (attempt_no >= 1),
        status TEXT NOT NULL CHECK ({check_in("status", ExecutionAttemptStatus)}),
        owner_token TEXT,
        lease_expires_at TEXT,
        started_at TEXT,
        completed_at TEXT,
        outcome TEXT,
        created_at TEXT NOT NULL
    )""",
    f"""CREATE TABLE resume_operations (
        id TEXT PRIMARY KEY NOT NULL,
        workflow_run_id TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE RESTRICT,
        approval_id TEXT NOT NULL REFERENCES approvals(id) ON DELETE RESTRICT,
        decision TEXT NOT NULL CHECK ({check_in_members("decision", _RESOLVED)}),
        status TEXT NOT NULL CHECK ({check_in("status", ResumeOperationStatus)}),
        langgraph_checkpoint_id TEXT,
        langgraph_interrupt_id TEXT,
        owner_token TEXT,
        lease_expires_at TEXT,
        completed_at TEXT,
        created_at TEXT NOT NULL
    )""",
)

WORKFLOW_INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX idx_run_task ON workflow_runs(task_id)",
    "CREATE UNIQUE INDEX ux_run_active_task ON workflow_runs(task_id) "
    f"WHERE status IN ({members_list(_ACTIVE_RUN)})",
    "CREATE INDEX idx_appr_run ON approvals(workflow_run_id)",
    "CREATE UNIQUE INDEX ux_appr_gate_instance ON approvals(gate_instance_id) "
    "WHERE gate_instance_id IS NOT NULL",
    "CREATE UNIQUE INDEX ux_appr_pending_run ON approvals(workflow_run_id) "
    f"WHERE status = '{ApprovalStatus.PENDING.value}' AND workflow_run_id IS NOT NULL",
    "CREATE INDEX idx_trans_run ON status_transitions(workflow_run_id, created_at)",
    "CREATE UNIQUE INDEX ux_trans_operation ON status_transitions(operation_id, subject)",
    "CREATE UNIQUE INDEX ux_attempt_no "
    "ON execution_attempts(workflow_run_id, logical_action_id, attempt_no)",
    "CREATE UNIQUE INDEX ux_attempt_active "
    "ON execution_attempts(workflow_run_id, logical_action_id) "
    f"WHERE status IN ({members_list(_ACTIVE_ATTEMPT)})",
    "CREATE INDEX idx_attempt_run ON execution_attempts(workflow_run_id)",
    "CREATE UNIQUE INDEX ux_resume_approval ON resume_operations(approval_id)",
    "CREATE UNIQUE INDEX ux_resume_interrupt "
    "ON resume_operations(workflow_run_id, langgraph_interrupt_id) "
    "WHERE langgraph_interrupt_id IS NOT NULL",
)

WORKFLOW_EXPECTED_SCHEMA: dict[str, frozenset[str]] = {
    "workflow_runs": frozenset(
        {
            "id",
            "task_id",
            "thread_id",
            "status",
            "workflow_definition_version",
            "initial_invoke_operation_id",
            "checkpoint_ever_observed",
            "last_observed_checkpoint_id",
            "cancel_requested_at",
            "created_at",
            "updated_at",
        }
    ),
    "status_transitions": frozenset(
        {
            "id",
            "workflow_run_id",
            "subject",
            "from_status",
            "to_status",
            "trigger",
            "operation_id",
            "causation_id",
            "created_at",
        }
    ),
    "execution_attempts": frozenset(
        {
            "id",
            "workflow_run_id",
            "logical_action_id",
            "attempt_no",
            "status",
            "owner_token",
            "lease_expires_at",
            "started_at",
            "completed_at",
            "outcome",
            "created_at",
        }
    ),
    "resume_operations": frozenset(
        {
            "id",
            "workflow_run_id",
            "approval_id",
            "decision",
            "status",
            "langgraph_checkpoint_id",
            "langgraph_interrupt_id",
            "owner_token",
            "lease_expires_at",
            "completed_at",
            "created_at",
        }
    ),
}

# Phase 4 columns added to the rebuilt approvals table (verified by the inspector).
APPROVALS_V2_COLUMNS: frozenset[str] = frozenset(
    {
        "workflow_run_id",
        "gate_type",
        "gate_instance_id",
        "approval_gate_sequence",
        "actor_source",
        "actor_label",
        "approval_row_version",
        "langgraph_checkpoint_id",
        "langgraph_interrupt_id",
        "request_json",
    }
)
