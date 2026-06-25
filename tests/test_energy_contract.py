"""CP7 energy contract tests: resource kinds, budget, status, errors."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.energy import (
    EnergyBudget,
    EnergyBudgetExceededError,
    EnergyError,
    EnergyReservationError,
    MeasurementStatus,
    ReservationStatus,
    ResourceKind,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.errors import AntError


class TestResourceKind:
    def test_all_kinds_have_stable_values(self) -> None:
        for kind in ResourceKind:
            assert isinstance(kind.value, str)
            assert kind.value

    def test_expected_kinds(self) -> None:
        names = {k.name for k in ResourceKind}
        assert names >= {"TOKENS", "API_CALLS", "WALL_TIME", "RETRIES", "HUMAN_APPROVALS"}

    def test_tokens_value(self) -> None:
        assert ResourceKind.TOKENS.value == "tokens"

    def test_wall_time_uses_ms(self) -> None:
        assert ResourceKind.WALL_TIME.value == "wall_time_ms"


class TestMeasurementStatus:
    def test_estimated_and_measured(self) -> None:
        assert MeasurementStatus.ESTIMATED.value == "estimated"
        assert MeasurementStatus.MEASURED.value == "measured"


class TestReservationStatus:
    def test_all_statuses(self) -> None:
        names = {s.name for s in ReservationStatus}
        assert names == {"RESERVED", "CONSUMED", "RELEASED", "EXPIRED"}

    def test_serialization(self) -> None:
        for s in ReservationStatus:
            assert isinstance(s.value, str)


class TestEnergyBudget:
    def test_valid_budget(self) -> None:
        b = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 5})
        assert b.limit_for(ResourceKind.TOKENS) == 1000
        assert b.limit_for(ResourceKind.API_CALLS) == 5

    def test_ungoverned_returns_none(self) -> None:
        b = EnergyBudget({ResourceKind.TOKENS: 1000})
        assert b.limit_for(ResourceKind.RETRIES) is None

    def test_zero_limit_allowed(self) -> None:
        b = EnergyBudget({ResourceKind.TOKENS: 0})
        assert b.limit_for(ResourceKind.TOKENS) == 0

    def test_negative_limit_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            EnergyBudget({ResourceKind.TOKENS: -1})

    def test_immutable_limits(self) -> None:
        b = EnergyBudget({ResourceKind.TOKENS: 1000})
        with pytest.raises(TypeError):
            b.limits[ResourceKind.TOKENS] = 0  # type: ignore[index]

    def test_defensive_copy(self) -> None:
        original = {ResourceKind.TOKENS: 1000}
        b = EnergyBudget(original)
        original[ResourceKind.TOKENS] = 0
        assert b.limit_for(ResourceKind.TOKENS) == 1000

    def test_equality(self) -> None:
        b1 = EnergyBudget({ResourceKind.TOKENS: 100})
        b2 = EnergyBudget({ResourceKind.TOKENS: 100})
        assert b1 == b2

    def test_empty_budget(self) -> None:
        b = EnergyBudget({})
        assert b.limit_for(ResourceKind.TOKENS) is None


class TestErrorTaxonomy:
    def test_energy_error_is_ant_error(self) -> None:
        assert issubclass(EnergyError, AntError)

    def test_budget_exceeded_is_energy_error(self) -> None:
        assert issubclass(EnergyBudgetExceededError, EnergyError)

    def test_reservation_error_is_energy_error(self) -> None:
        assert issubclass(EnergyReservationError, EnergyError)

    def test_budget_error_not_context_error(self) -> None:
        from ant_orchestrator.application.ports.context_builder import (
            ContextBudgetExceededError,
        )

        assert not issubclass(EnergyBudgetExceededError, ContextBudgetExceededError)
        assert not issubclass(ContextBudgetExceededError, EnergyBudgetExceededError)
