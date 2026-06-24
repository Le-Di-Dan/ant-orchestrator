"""Unit tests for the timeout resolution policy (CP2; float semantics)."""

from __future__ import annotations

import math

import pytest

from ant_orchestrator.config.constants import (
    DEFAULT_TIMEOUT_SECONDS,
    MAX_TIMEOUT_SECONDS,
)
from ant_orchestrator.config.errors import ConfigInvalid
from ant_orchestrator.config.timeout import resolve_timeout, validate_timeout

# --- precedence ---------------------------------------------------------------


def test_request_overrides_endpoint() -> None:
    assert resolve_timeout(30.5, 60.0) == pytest.approx(30.5)


def test_endpoint_used_when_request_absent() -> None:
    assert resolve_timeout(None, 60.5) == pytest.approx(60.5)


def test_default_used_when_both_absent() -> None:
    assert resolve_timeout(None, None) == DEFAULT_TIMEOUT_SECONDS
    assert DEFAULT_TIMEOUT_SECONDS == 120.0


def test_integer_input_is_accepted_and_returned_as_float() -> None:
    result = resolve_timeout(30, 60)
    assert result == 30.0
    assert isinstance(result, float)


def test_result_is_always_float() -> None:
    assert isinstance(resolve_timeout(None, None), float)
    assert isinstance(resolve_timeout(0.1, None), float)
    assert isinstance(resolve_timeout(None, 600.0), float)


# --- boundaries ---------------------------------------------------------------


@pytest.mark.parametrize("good", [0.1, 30, 30.5, 600, 600.0])
def test_valid_values_accepted(good: float) -> None:
    assert resolve_timeout(good, None) == pytest.approx(float(good))


def test_request_at_maximum_is_accepted() -> None:
    assert resolve_timeout(MAX_TIMEOUT_SECONDS, None) == 600.0


@pytest.mark.parametrize("bad", [0, -1, 601, 600.1, -0.5])
def test_invalid_request_timeout_rejected(bad: float) -> None:
    with pytest.raises(ConfigInvalid):
        resolve_timeout(bad, None)


@pytest.mark.parametrize("bad", [0, -1, 601, 600.1])
def test_invalid_endpoint_timeout_rejected(bad: float) -> None:
    with pytest.raises(ConfigInvalid):
        resolve_timeout(None, bad)


# --- special values -----------------------------------------------------------


@pytest.mark.parametrize("bad", [True, False])
def test_boolean_timeout_rejected(bad: bool) -> None:
    with pytest.raises(ConfigInvalid):
        validate_timeout(bad)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_timeout_rejected(bad: float) -> None:
    with pytest.raises(ConfigInvalid):
        validate_timeout(bad)


def test_resolver_does_not_clamp_high_value() -> None:
    # An out-of-range value must raise, never be silently reduced to the maximum.
    with pytest.raises(ConfigInvalid):
        resolve_timeout(5000.0, None)


def test_validate_timeout_returns_value_unchanged() -> None:
    assert validate_timeout(45.5) == pytest.approx(45.5)
    assert validate_timeout(MAX_TIMEOUT_SECONDS) == 600.0
