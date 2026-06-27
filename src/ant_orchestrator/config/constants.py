"""Configuration constants — single source of truth (PHASE_1_PLAN §11)."""

from __future__ import annotations

from typing import Final

# Config DOCUMENT version (distinct from workspace format & DB schema version, D12).
CONFIG_DOCUMENT_VERSION: Final = 1

CONFIG_FILENAME: Final = "config.yaml"
DEFAULT_PROJECT_NAME: Final = "unnamed"

# Environment overrides (only string-valued fields, to avoid coercion — §11.6).
ENV_PREFIX: Final = "ANT_"
ENV_PROJECT_NAME: Final = "ANT_PROJECT_NAME"

# Document keys and their allowed sets (unknown keys rejected at every level).
KEY_VERSION: Final = "version"
KEY_PROJECT: Final = "project"
KEY_PROJECT_NAME: Final = "name"
KEY_MODELS: Final = "models"
ALLOWED_TOP_LEVEL_KEYS: Final = frozenset({KEY_VERSION, KEY_PROJECT, KEY_MODELS})
ALLOWED_PROJECT_KEYS: Final = frozenset({KEY_PROJECT_NAME})

# Optional model-endpoint section (provider-neutral; no secret/api-key fields, D12).
KEY_MODELS_QUEEN: Final = "queen"
KEY_MODELS_LOCAL: Final = "local"
ALLOWED_MODELS_KEYS: Final = frozenset({KEY_MODELS_QUEEN, KEY_MODELS_LOCAL})

KEY_ENDPOINT_PROVIDER: Final = "provider"
KEY_ENDPOINT_MODEL: Final = "model"
KEY_ENDPOINT_TIMEOUT: Final = "timeout_seconds"
KEY_ENDPOINT_BASE_URL: Final = "base_url"
ALLOWED_ENDPOINT_KEYS: Final = frozenset(
    {KEY_ENDPOINT_PROVIDER, KEY_ENDPOINT_MODEL, KEY_ENDPOINT_TIMEOUT, KEY_ENDPOINT_BASE_URL}
)

# Timeout policy (seconds, float). Single source of truth; never hard-coded in
# adapters. Resolved timeouts are always float so they line up directly with
# ``LLMRequest.timeout_seconds`` (float | None).
DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
MAX_TIMEOUT_SECONDS: Final[float] = 600.0

# Execution boundary constants (CP3).
DEFAULT_COMMAND_TIMEOUT_SECONDS: Final[float] = 30.0
MAX_COMMAND_TIMEOUT_SECONDS: Final[float] = 300.0
DEFAULT_MAX_OUTPUT_BYTES: Final = 65536
OUTPUT_TRUNCATION_MARKER: Final = "\n... [OUTPUT TRUNCATED]"
REDACTION_SAFETY_MARGIN_BYTES: Final = 256
DRAIN_CHUNK_SIZE: Final = 4096
PROCESS_KILL_GRACE_SECONDS: Final[float] = 5.0
DEFAULT_MAX_READ_BYTES: Final = 1048576

# Context estimation constants (CP5).
TOKEN_ESTIMATION_DEFAULT_DIVISOR: Final = 4

# Phase 4 workflow constants (CP2). Schema/topology versions are code constants;
# the retry/regroup bounds are policy defaults (config-overridable in a later phase).
GRAPH_STATE_SCHEMA_VERSION: Final = 1
# Bumped to 2 in CP4: the topology gained the approval-interrupt path (prepare_intent
# / await_approval / rejected / cancelled) and dropped the gate_blocked placeholder.
WORKFLOW_DEFINITION_VERSION: Final = 2
WORKFLOW_MAX_RETRIES: Final = 2
WORKFLOW_MAX_RETRY_EXTENSIONS: Final = 1
WORKFLOW_MAX_REGROUPS: Final = 1

# Milliseconds a write unit of work waits for a contended SQLite lock before giving
# up. Paired with ``BEGIN IMMEDIATE`` it lets concurrent writers (e.g. two ``approve``
# processes) serialize cleanly instead of dead-locking on a read-then-upgrade.
SQLITE_BUSY_TIMEOUT_MS: Final = 5000

# CP4/CP5 coordination constants. Lease durations bound how long an owner may hold
# the right to drive a graph operation before recovery may reclaim it.
RESUME_LEASE_SECONDS: Final = 300
EXECUTION_ATTEMPT_LEASE_SECONDS: Final = 300
# Deterministic operation-id prefixes (idempotency keys for status transitions).
PAUSE_OPERATION_PREFIX: Final = "pause-"
COMPLETION_OPERATION_PREFIX: Final = "complete-"
# CP6 — non-terminal status string for RUNNING cancellation (not a TaskStatus enum).
CANCEL_REQUESTED_STATUS: Final = "cancel_requested"
CANCEL_REQUEST_OPERATION_PREFIX: Final = "cancel-request-"
# CP7 — version stamped into every Phase 4 ``--json`` CLI payload (single source).
CLI_JSON_SCHEMA_VERSION: Final = 1
# CP7 — ``ant status`` shows at most this many most-recent tasks (no pagination yet).
STATUS_RECENT_TASK_LIMIT: Final = 50
# CP7 — a rejection reason is sanitized and bounded to this many characters.
MAX_REJECT_REASON_CHARS: Final = 500
