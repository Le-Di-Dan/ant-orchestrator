"""CP7 energy measurement tests: resource amounts, status, invariants."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.energy import MeasurementStatus, ResourceKind
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.energy.measurement import EnergyMeasurement, ResourceAmount

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))


class TestResourceAmount:
    def test_valid(self) -> None:
        a = ResourceAmount(ResourceKind.TOKENS, 100)
        assert a.kind is ResourceKind.TOKENS
        assert a.amount == 100

    def test_zero_allowed(self) -> None:
        a = ResourceAmount(ResourceKind.API_CALLS, 0)
        assert a.amount == 0

    def test_negative_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ResourceAmount(ResourceKind.TOKENS, -1)

    def test_frozen(self) -> None:
        a = ResourceAmount(ResourceKind.TOKENS, 100)
        with pytest.raises(AttributeError):
            a.amount = 0  # type: ignore[misc]


class TestEnergyMeasurement:
    def test_estimated_tokens(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 500),),
            status=MeasurementStatus.ESTIMATED,
            recorded_at=_TS,
        )
        assert m.status is MeasurementStatus.ESTIMATED
        assert m.amount_for(ResourceKind.TOKENS) == 500

    def test_measured_tokens(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 420),),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
        )
        assert m.status is MeasurementStatus.MEASURED
        assert m.amount_for(ResourceKind.TOKENS) == 420

    def test_multiple_resources(self) -> None:
        m = EnergyMeasurement(
            amounts=(
                ResourceAmount(ResourceKind.TOKENS, 100),
                ResourceAmount(ResourceKind.API_CALLS, 1),
                ResourceAmount(ResourceKind.WALL_TIME, 5000),
            ),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
        )
        assert m.amount_for(ResourceKind.TOKENS) == 100
        assert m.amount_for(ResourceKind.API_CALLS) == 1
        assert m.amount_for(ResourceKind.WALL_TIME) == 5000

    def test_missing_resource_returns_zero(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 100),),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
        )
        assert m.amount_for(ResourceKind.RETRIES) == 0

    def test_zero_usage(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 0),),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
        )
        assert m.amount_for(ResourceKind.TOKENS) == 0

    def test_duplicate_resource_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            EnergyMeasurement(
                amounts=(
                    ResourceAmount(ResourceKind.TOKENS, 100),
                    ResourceAmount(ResourceKind.TOKENS, 200),
                ),
                status=MeasurementStatus.MEASURED,
                recorded_at=_TS,
            )

    def test_correlation_id(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 100),),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
            correlation_id="corr-1",
        )
        assert m.correlation_id == "corr-1"

    def test_frozen(self) -> None:
        m = EnergyMeasurement(
            amounts=(ResourceAmount(ResourceKind.TOKENS, 100),),
            status=MeasurementStatus.MEASURED,
            recorded_at=_TS,
        )
        with pytest.raises(AttributeError):
            m.status = MeasurementStatus.ESTIMATED  # type: ignore[misc]

    def test_empty_amounts_valid(self) -> None:
        m = EnergyMeasurement(
            amounts=(),
            status=MeasurementStatus.ESTIMATED,
            recorded_at=_TS,
        )
        assert m.amount_for(ResourceKind.TOKENS) == 0
