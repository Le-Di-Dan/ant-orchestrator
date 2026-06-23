"""Unit tests for the optional ``models`` config section (CP2)."""

from __future__ import annotations

import pytest

from ant_orchestrator.config.errors import ConfigInvalid, UnknownConfigKey
from ant_orchestrator.config.models import ModelsConfig
from ant_orchestrator.config.resolver import ConfigResolver


def _resolve(models: object) -> ModelsConfig:
    cfg = ConfigResolver().resolve(file_data={"version": 1, "models": models}, env={})
    return cfg.models


# --- backward compatibility ---------------------------------------------------


def test_phase1_config_without_models_loads_empty() -> None:
    cfg = ConfigResolver().resolve(file_data={"version": 1, "project": {"name": "x"}}, env={})
    assert cfg.models == ModelsConfig()
    assert cfg.models.queen is None
    assert cfg.models.local is None


def test_empty_models_section_is_valid() -> None:
    assert _resolve({}) == ModelsConfig()


# --- valid endpoints ----------------------------------------------------------


def test_valid_queen_endpoint() -> None:
    models = _resolve(
        {"queen": {"provider": "openai", "model": "example-model", "timeout_seconds": 60}}
    )
    assert models.queen is not None
    assert models.queen.provider == "openai"
    assert models.queen.model == "example-model"
    assert models.queen.timeout_seconds == 60
    assert models.queen.base_url is None
    assert models.local is None


def test_valid_local_ollama_endpoint() -> None:
    models = _resolve(
        {
            "local": {
                "provider": "ollama",
                "model": "example-local-model",
                "base_url": "http://localhost:11434",
                "timeout_seconds": 120,
            }
        }
    )
    assert models.local is not None
    assert models.local.provider == "ollama"
    assert models.local.base_url == "http://localhost:11434"


def test_endpoint_without_optional_fields() -> None:
    models = _resolve({"queen": {"provider": "openai", "model": "m"}})
    assert models.queen is not None
    assert models.queen.timeout_seconds is None
    assert models.queen.base_url is None


# --- required fields / validation --------------------------------------------


def test_endpoint_missing_provider_rejected() -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"model": "m"}})


def test_endpoint_missing_model_rejected() -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": "openai"}})


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_or_whitespace_provider_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": bad, "model": "m"}})


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_or_whitespace_model_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": "openai", "model": bad}})


@pytest.mark.parametrize("bad", [" openai", "openai ", " openai "])
def test_provider_with_surrounding_whitespace_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": bad, "model": "m"}})


@pytest.mark.parametrize("bad", [" example-model", "example-model ", " example-model "])
def test_model_with_surrounding_whitespace_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": "openai", "model": bad}})


@pytest.mark.parametrize("bad", [" http://localhost:11434", "http://localhost:11434 "])
def test_base_url_with_surrounding_whitespace_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"local": {"provider": "ollama", "model": "m", "base_url": bad}})


def test_internal_whitespace_in_identifier_is_allowed() -> None:
    # Only *surrounding* whitespace is rejected; internal characters are verbatim.
    models = _resolve({"queen": {"provider": "openai", "model": "model-a b"}})
    assert models.queen is not None
    assert models.queen.model == "model-a b"


def test_unknown_models_key_rejected() -> None:
    with pytest.raises(UnknownConfigKey):
        _resolve({"bogus": {"provider": "openai", "model": "m"}})


def test_unknown_endpoint_key_rejected() -> None:
    with pytest.raises(UnknownConfigKey):
        _resolve({"queen": {"provider": "openai", "model": "m", "extra": 1}})


@pytest.mark.parametrize("secret_key", ["api_key", "secret", "token"])
def test_secret_fields_in_config_rejected(secret_key: str) -> None:
    with pytest.raises(UnknownConfigKey):
        _resolve({"queen": {"provider": "openai", "model": "m", secret_key: "x"}})


def test_models_must_be_mapping() -> None:
    with pytest.raises(ConfigInvalid):
        _resolve("oops")


def test_endpoint_must_be_mapping() -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": "oops"})


# --- endpoint timeout bounds (rejected before any invocation) ----------------


@pytest.mark.parametrize("bad", [0, -1, 601, 600.1])
def test_endpoint_timeout_out_of_range_rejected(bad: float) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": "openai", "model": "m", "timeout_seconds": bad}})


def test_endpoint_timeout_at_maximum_is_accepted() -> None:
    models = _resolve({"queen": {"provider": "openai", "model": "m", "timeout_seconds": 600}})
    assert models.queen is not None
    assert models.queen.timeout_seconds == 600.0


def test_endpoint_integer_timeout_normalized_to_float() -> None:
    models = _resolve({"queen": {"provider": "openai", "model": "m", "timeout_seconds": 60}})
    assert models.queen is not None
    assert isinstance(models.queen.timeout_seconds, float)
    assert models.queen.timeout_seconds == 60.0


def test_endpoint_fractional_timeout_preserved() -> None:
    models = _resolve({"local": {"provider": "ollama", "model": "m", "timeout_seconds": 30.5}})
    assert models.local is not None
    assert models.local.timeout_seconds == pytest.approx(30.5)


@pytest.mark.parametrize("bad", ["60", True])
def test_endpoint_timeout_must_be_a_number(bad: object) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"queen": {"provider": "openai", "model": "m", "timeout_seconds": bad}})


# --- base_url -----------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "   "])
def test_empty_base_url_rejected(bad: str) -> None:
    with pytest.raises(ConfigInvalid):
        _resolve({"local": {"provider": "ollama", "model": "m", "base_url": bad}})
