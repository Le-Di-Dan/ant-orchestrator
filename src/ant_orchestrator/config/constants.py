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
# Phase 5 CP2 bumped 1→2: graph state now carries the prepared ``context_package_ref``
# and ``manifest_digest`` (anti-TOCTOU binding). A pre-CP2 checkpoint lacks them, so it
# must fail closed (GraphStateSchemaMismatch) instead of resuming without a digest.
GRAPH_STATE_SCHEMA_VERSION: Final = 2
# Phase 5 CP6 bumps the definition 2→3: the workflow now drives a real side-effecting
# Documentation Ant (proposal/approval binding, durable persistence, recovery), so a
# pre-CP6 (definition-2) checkpoint must fail closed (WorkflowDefinitionMismatch) rather
# than resume under the new execution semantics. The state schema stays 2: CP6 only adds
# OPTIONAL JSON-safe state fields (proposal/approval/attempt/report refs), so a schema-2
# checkpoint still round-trips — the runtime invariants (not the schema) enforce them on
# the Phase 5 production path.
WORKFLOW_DEFINITION_VERSION: Final = 4
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

# --- Phase 5 CP6: durable documentation-ant integration ----------------------
# Worker-kind tag folded into the deterministic ``WorkerRunId`` so two worker types
# acting on the same logical action can never collide on one run identity.
DOC_WORKER_KIND: Final = "documentation"
# Versioned, typed evidence envelope persisted in the existing ``evidence.result``
# column (no schema migration in CP6). The validator rejects any other version.
EVIDENCE_ENVELOPE_SCHEMA_VERSION: Final = 1
# Hard upper bound on the serialized evidence envelope (sanitized refs only — never a
# raw prompt, provider output, or artifact payload).
MAX_EVIDENCE_ENVELOPE_BYTES: Final = 16_384
# CP7 — a rejection reason is sanitized and bounded to this many characters.
MAX_REJECT_REASON_CHARS: Final = 500

# Phase 5 CP4 — durable single-document mutation. The journal schema is owned here
# (bumped on any journal field/semantics change). Each system artifact is byte-bounded.
JOURNAL_SCHEMA_VERSION: Final = 1
MAX_ARTIFACT_BYTES: Final = 1_048_576
# Bytes read for the authoritative BEFORE snapshot of an UPDATE target (sync, bounded —
# the async BoundedFileSystemAdapter is bridged only from CP5).
MAX_BEFORE_READ_BYTES: Final = 1_048_576

# Phase 5 CP5 — Documentation Ant, provider-neutral composition, durable receipt.
# The composition receipt schema is owned here (bumped on any field/semantics change).
COMPOSITION_RECEIPT_SCHEMA_VERSION: Final = 1
# Stable prompt template identity persisted into the receipt (never the prompt CONTENT).
DOC_PROMPT_TEMPLATE_ID: Final = "documentation.compose"
DOC_PROMPT_TEMPLATE_VERSION: Final = 1
# Sanitized provider/model identifiers persisted into the receipt are bounded.
MAX_PROVIDER_ID_CHARS: Final = 64
# A raw model output larger than this is rejected before parsing (defence-in-depth).
MAX_MODEL_OUTPUT_CHARS: Final = 400_000

# Phase 6 CP2 — enforceable Test Ant container isolation (ADR-0007). The MVP backend is
# local Docker pinned to an IMMUTABLE, content-addressable image identity (the sha256
# image ID), verified present at preflight and NEVER pulled at run time. The host uses the
# containerd image store, where the image ID — not the mutable tag or a registry
# RepoDigest — is the form both ``docker image inspect`` and ``docker run`` resolve.
TEST_ISOLATION_IMAGE_REPO: Final = "python"
TEST_ISOLATION_IMAGE_ID: Final = (
    "sha256:9800957d2a88867f853ce6072ae1669e37fa269cc6f76009fa1aef4757f62212"
)
TEST_ISOLATION_IMAGE_REF: Final = TEST_ISOLATION_IMAGE_ID
# Deterministic container identity + least-privilege runtime limits (validated on host).
TEST_CONTAINER_NAME_PREFIX: Final = "ant-test-"
TEST_CONTAINER_USER: Final = "1000:1000"
TEST_CONTAINER_PIDS_LIMIT: Final = 256
TEST_CONTAINER_MEMORY: Final = "512m"
TEST_CONTAINER_TMPFS_SIZE: Final = "64m"
TEST_CONTAINER_WORK_MOUNT: Final = "/work"
TEST_CONTAINER_OUT_MOUNT: Final = "/out"
TEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS: Final[float] = 120.0
# Exact-byte snapshot bounds (defence-in-depth against runaway scope).
MAX_SNAPSHOT_FILES: Final = 5000
MAX_SNAPSHOT_TOTAL_BYTES: Final = 67_108_864
MAX_SNAPSHOT_FILE_BYTES: Final = 8_388_608

# --- Phase 6 CP3: Test Ant worker, structured report & classifier ------------
# Worker-kind tag for the Test Ant (mirrors DOC_WORKER_KIND; folded into identity).
TEST_WORKER_KIND: Final = "test"
# The structured test report schema is owned here (bumped on any field/semantics change).
TEST_REPORT_SCHEMA_VERSION: Final = 1
# Bounds on the sanitized, durable-facing StructuredTestReport (no raw output/host path).
MAX_TEST_DIAGNOSTIC_HINT_CHARS: Final = 240
MAX_TEST_FAILURE_EXCERPTS: Final = 8
MAX_TEST_EXCERPT_CHARS: Final = 200
MAX_TEST_EVIDENCE_REFS: Final = 16
MAX_TEST_REPORT_TARGETS: Final = 64
# Inner pytest acceptance-profile exit-code semantics (pure, profile-owned — never the
# generic isolation port). See https://docs.pytest.org/en/stable/reference/exit-codes.html
PYTEST_EXIT_OK: Final = 0
PYTEST_EXIT_TESTS_FAILED: Final = 1
PYTEST_EXIT_INTERRUPTED: Final = 2
PYTEST_EXIT_INTERNAL_ERROR: Final = 3
PYTEST_EXIT_USAGE_ERROR: Final = 4
PYTEST_EXIT_NO_TESTS_COLLECTED: Final = 5

# --- Phase 6 CP5: structured test evidence, delta energy & terminal handoff ---
# Test evidence envelope stored in execution_evidence.result (version 2 discriminates
# from DocAnt evidence version 1).  Same MAX_EVIDENCE_ENVELOPE_BYTES limit applies.
TEST_EVIDENCE_ENVELOPE_SCHEMA_VERSION: Final = 2
# Terminal handoff JSON payload stored in handoff_records.what_changed.
TERMINAL_HANDOFF_SCHEMA_VERSION: Final = 1
MAX_TERMINAL_HANDOFF_BYTES: Final = 8_192
MAX_HANDOFF_SUMMARY_CHARS: Final = 400
MAX_HANDOFF_NEXT_STEPS_CHARS: Final = 400

# --- Phase 7: memory retrieval limits and API bind surface -------------------
MEMORY_DEFAULT_LIMIT: Final = 20
MEMORY_MAX_LIMIT: Final = 100

LOG_DEFAULT_LIMIT: Final = 50
LOG_MAX_LIMIT: Final = 200

API_BIND_HOST: Final = "127.0.0.1"
API_BIND_PORT: Final = 8080

TASK_DETAIL_WORKER_RUN_LIMIT: Final = 100
TASK_DETAIL_APPROVAL_LIMIT: Final = 100
WORKER_RUN_DETAIL_EVIDENCE_LIMIT: Final = 50

# --- Phase 8 CP4: Task result and artifact persistence -----------------------
TASK_RESULT_VERSION: Final = 1
MAX_TASK_RESULT_SUMMARY_CHARS: Final = 2000
MAX_FAILURE_MESSAGE_CHARS: Final = 500
MAX_FAILURE_CODE_CHARS: Final = 80
MAX_FAILURE_SOURCE_CHARS: Final = 80
MAX_ARTIFACT_METADATA_BYTES: Final = 4096
MAX_ARTIFACT_PATH_CHARS: Final = 512
MAX_ARTIFACT_MEDIA_TYPE_CHARS: Final = 128
ARTIFACT_SHA256_HEX_LENGTH: Final = 64

# --- Phase 8 CP5: CLI productization -----------------------------------------
# Single source of truth for the CLI version.  Used by --version, doctor JSON,
# and any future packaging layer (wheel metadata, native binary, npm root pkg).
ANT_CLI_VERSION: Final = "0.1.0"
# Schema version for the doctor JSON payload (bumped on any field/semantics change).
DOCTOR_JSON_SCHEMA_VERSION: Final = 1
# Expected SQLite schema version after all migrations have run (v5 = CP4).
EXPECTED_DB_SCHEMA_VERSION: Final = 5
# Supported providers for the configure command.
CONFIGURE_SUPPORTED_PROVIDERS: Final = frozenset({"openai", "ollama"})
# Provider → env-var that holds the API key (ollama has no key requirement).
PROVIDER_KEY_ENV: Final[dict[str, str]] = {"openai": "OPENAI_API_KEY"}
