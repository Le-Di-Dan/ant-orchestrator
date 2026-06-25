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
