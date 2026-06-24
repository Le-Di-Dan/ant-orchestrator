"""Configuration resolution with precedence: defaults < file < environment.

Rejects unknown keys at every level and performs no silent coercion (PHASE_1_PLAN
§11.3/§11.6). Environment overrides apply only to string-valued fields.
"""

from __future__ import annotations

from collections.abc import Mapping

from ant_orchestrator.config.constants import (
    ALLOWED_ENDPOINT_KEYS,
    ALLOWED_MODELS_KEYS,
    ALLOWED_PROJECT_KEYS,
    ALLOWED_TOP_LEVEL_KEYS,
    CONFIG_DOCUMENT_VERSION,
    DEFAULT_PROJECT_NAME,
    ENV_PROJECT_NAME,
    KEY_ENDPOINT_BASE_URL,
    KEY_ENDPOINT_MODEL,
    KEY_ENDPOINT_PROVIDER,
    KEY_ENDPOINT_TIMEOUT,
    KEY_MODELS,
    KEY_MODELS_LOCAL,
    KEY_MODELS_QUEEN,
    KEY_PROJECT,
    KEY_PROJECT_NAME,
    KEY_VERSION,
)
from ant_orchestrator.config.errors import ConfigInvalid, UnknownConfigKey
from ant_orchestrator.config.loader import as_str_keyed
from ant_orchestrator.config.models import (
    ModelEndpointConfig,
    ModelsConfig,
    ProjectConfig,
    ResolvedConfig,
)
from ant_orchestrator.config.timeout import validate_timeout


def _default_config() -> ResolvedConfig:
    return ResolvedConfig(
        version=CONFIG_DOCUMENT_VERSION,
        project=ProjectConfig(name=DEFAULT_PROJECT_NAME),
    )


def _reject_unknown(data: Mapping[str, object], allowed: frozenset[str], scope: str) -> None:
    unknown = set(data) - allowed
    if unknown:
        raise UnknownConfigKey(f"Unknown {scope} keys: {sorted(unknown)}")


class ConfigResolver:
    """Merges defaults, a parsed file document and the environment into config."""

    def __init__(self, defaults: ResolvedConfig | None = None) -> None:
        self._defaults = defaults if defaults is not None else _default_config()

    def resolve(
        self,
        *,
        file_data: Mapping[str, object],
        env: Mapping[str, str],
    ) -> ResolvedConfig:
        """Resolve config applying precedence; raises on unknown keys/invalid types."""
        _reject_unknown(file_data, ALLOWED_TOP_LEVEL_KEYS, "config")
        version = self._resolve_version(file_data)
        name = self._resolve_name(file_data, env)
        models = self._resolve_models(file_data)
        return ResolvedConfig(version=version, project=ProjectConfig(name=name), models=models)

    def _resolve_version(self, file_data: Mapping[str, object]) -> int:
        raw = file_data.get(KEY_VERSION)
        if raw is None:
            return self._defaults.version
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ConfigInvalid("version must be an integer")
        if raw < 1:
            raise ConfigInvalid("version must be >= 1")
        return raw

    def _resolve_name(self, file_data: Mapping[str, object], env: Mapping[str, str]) -> str:
        name = self._defaults.project.name
        project_raw = file_data.get(KEY_PROJECT)
        if project_raw is not None:
            if not isinstance(project_raw, dict):
                raise ConfigInvalid("project must be a mapping")
            project = as_str_keyed(project_raw)
            _reject_unknown(project, ALLOWED_PROJECT_KEYS, "project")
            name_raw = project.get(KEY_PROJECT_NAME)
            if name_raw is not None:
                if not isinstance(name_raw, str):
                    raise ConfigInvalid("project.name must be a string")
                name = name_raw
        env_name = env.get(ENV_PROJECT_NAME)
        if env_name is not None:
            name = env_name
        return name

    def _resolve_models(self, file_data: Mapping[str, object]) -> ModelsConfig:
        raw = file_data.get(KEY_MODELS)
        if raw is None:
            return ModelsConfig()
        if not isinstance(raw, dict):
            raise ConfigInvalid("models must be a mapping")
        models = as_str_keyed(raw)
        _reject_unknown(models, ALLOWED_MODELS_KEYS, "models")
        return ModelsConfig(
            queen=self._resolve_endpoint(models.get(KEY_MODELS_QUEEN), "models.queen"),
            local=self._resolve_endpoint(models.get(KEY_MODELS_LOCAL), "models.local"),
        )

    def _resolve_endpoint(self, raw: object, scope: str) -> ModelEndpointConfig | None:
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ConfigInvalid(f"{scope} must be a mapping")
        endpoint = as_str_keyed(raw)
        _reject_unknown(endpoint, ALLOWED_ENDPOINT_KEYS, scope)
        return ModelEndpointConfig(
            provider=self._require_str(endpoint, KEY_ENDPOINT_PROVIDER, scope),
            model=self._require_str(endpoint, KEY_ENDPOINT_MODEL, scope),
            timeout_seconds=self._endpoint_timeout(endpoint, scope),
            base_url=self._optional_str(endpoint, KEY_ENDPOINT_BASE_URL, scope),
        )

    def _require_str(self, data: Mapping[str, object], key: str, scope: str) -> str:
        value = self._optional_str(data, key, scope)
        if value is None:
            raise ConfigInvalid(f"{scope}.{key} is required")
        return value

    def _optional_str(self, data: Mapping[str, object], key: str, scope: str) -> str | None:
        value = data.get(key)
        if value is None:
            return None
        if not isinstance(value, str):
            raise ConfigInvalid(f"{scope}.{key} must be a string")
        # Identifiers are used verbatim by the factory: reject empty, whitespace-only
        # and any surrounding whitespace. Never auto-strip/normalize the value.
        if not value or value != value.strip():
            raise ConfigInvalid(
                f"{scope}.{key} must be non-empty and free of surrounding whitespace"
            )
        return value

    def _endpoint_timeout(self, data: Mapping[str, object], scope: str) -> float | None:
        value = data.get(KEY_ENDPOINT_TIMEOUT)
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ConfigInvalid(f"{scope}.{KEY_ENDPOINT_TIMEOUT} must be a number")
        return validate_timeout(value, scope=f"{scope}.{KEY_ENDPOINT_TIMEOUT}")
