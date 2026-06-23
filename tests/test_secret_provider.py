"""Unit tests for SecretProvider semantics and secret hygiene (CP2)."""

from __future__ import annotations

from dataclasses import fields

import pytest

from ant_orchestrator.adapters.env_secret_provider import EnvSecretProvider
from ant_orchestrator.application.ports.secrets import SecretProvider
from ant_orchestrator.config.models import ModelEndpointConfig
from tests.support.fake_secret_provider import FakeSecretProvider

_ENV_NAME = "ANT_TEST_SECRET_CP2"
_SECRET_VALUE = "super-secret-value-123"


# --- EnvSecretProvider semantics ---------------------------------------------


def test_env_missing_secret_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_ENV_NAME, raising=False)
    assert EnvSecretProvider().get(_ENV_NAME) is None


def test_env_empty_secret_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_NAME, "")
    assert EnvSecretProvider().get(_ENV_NAME) is None


def test_env_present_secret_returned_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_ENV_NAME, _SECRET_VALUE)
    assert EnvSecretProvider().get(_ENV_NAME) == _SECRET_VALUE


def test_env_secret_with_surrounding_space_not_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_NAME, "  spaced  ")
    assert EnvSecretProvider().get(_ENV_NAME) == "  spaced  "


# --- FakeSecretProvider semantics --------------------------------------------


def test_fake_returns_scripted_secret() -> None:
    provider = FakeSecretProvider({_ENV_NAME: _SECRET_VALUE})
    assert provider.get(_ENV_NAME) == _SECRET_VALUE


def test_fake_missing_returns_none() -> None:
    assert FakeSecretProvider().get("absent") is None


def test_fake_empty_returns_none() -> None:
    assert FakeSecretProvider({_ENV_NAME: ""}).get(_ENV_NAME) is None


def test_whitespace_only_secret_is_a_value_and_returned_verbatim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Secret semantics differ from config identifiers: only "" -> None; a
    # whitespace-only value is a real secret and is returned unchanged (no strip).
    monkeypatch.setenv(_ENV_NAME, "   ")
    assert EnvSecretProvider().get(_ENV_NAME) == "   "
    assert FakeSecretProvider({_ENV_NAME: "   "}).get(_ENV_NAME) == "   "


# --- conformance & hygiene ----------------------------------------------------


def test_both_implementations_satisfy_the_port() -> None:
    assert isinstance(EnvSecretProvider(), SecretProvider)
    assert isinstance(FakeSecretProvider(), SecretProvider)


def test_fake_repr_does_not_reveal_secret() -> None:
    provider = FakeSecretProvider({_ENV_NAME: _SECRET_VALUE})
    assert _SECRET_VALUE not in repr(provider)


def test_env_provider_is_stateless_repr_has_no_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_ENV_NAME, _SECRET_VALUE)
    provider = EnvSecretProvider()
    provider.get(_ENV_NAME)
    assert _SECRET_VALUE not in repr(provider)


def test_model_endpoint_config_has_no_secret_field() -> None:
    names = {f.name for f in fields(ModelEndpointConfig)}
    assert names == {"provider", "model", "timeout_seconds", "base_url"}
    assert not (names & {"api_key", "secret", "token", "password"})
