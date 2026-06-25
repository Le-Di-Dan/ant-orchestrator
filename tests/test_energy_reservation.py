"""CP7 energy reservation ledger tests: reserve, consume, release, lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ant_orchestrator.application.ports.energy import (
    EnergyBudget,
    EnergyBudgetExceededError,
    EnergyReservationError,
    ReservationStatus,
    ResourceKind,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.energy.reservation import (
    ReservationLedger,
)
from tests.conftest import FakeClock, SequentialIdGenerator

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_BUDGET = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 10})


def _ledger(budget: EnergyBudget = _BUDGET) -> ReservationLedger:
    return ReservationLedger(budget, FakeClock(_TS), SequentialIdGenerator())


class TestReserve:
    def test_sufficient_budget(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        assert r.status is ReservationStatus.RESERVED
        assert r.amounts[ResourceKind.TOKENS] == 100

    def test_exact_boundary(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 1000})
        assert r.status is ReservationStatus.RESERVED

    def test_boundary_plus_one(self) -> None:
        led = _ledger()
        with pytest.raises(EnergyBudgetExceededError):
            led.reserve({ResourceKind.TOKENS: 1001})

    def test_multi_resource_atomic_success(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 500, ResourceKind.API_CALLS: 3})
        assert r.amounts[ResourceKind.TOKENS] == 500
        assert r.amounts[ResourceKind.API_CALLS] == 3

    def test_multi_resource_atomic_failure(self) -> None:
        led = _ledger()
        with pytest.raises(EnergyBudgetExceededError):
            led.reserve({ResourceKind.TOKENS: 500, ResourceKind.API_CALLS: 11})
        assert led.available(ResourceKind.TOKENS) == 1000
        assert led.available(ResourceKind.API_CALLS) == 10

    def test_zero_amount(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 0})
        assert r.status is ReservationStatus.RESERVED

    def test_ungoverned_resource_allowed(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.RETRIES: 5})
        assert r.status is ReservationStatus.RESERVED

    def test_empty_request_rejected(self) -> None:
        led = _ledger()
        with pytest.raises(InvariantViolation):
            led.reserve({})

    def test_negative_amount_rejected(self) -> None:
        led = _ledger()
        with pytest.raises(InvariantViolation):
            led.reserve({ResourceKind.TOKENS: -1})

    def test_failed_reserve_no_mutation(self) -> None:
        led = _ledger()
        led.reserve({ResourceKind.TOKENS: 900})
        with pytest.raises(EnergyBudgetExceededError):
            led.reserve({ResourceKind.TOKENS: 200})
        assert led.available(ResourceKind.TOKENS) == 100

    def test_available_after_reserve(self) -> None:
        led = _ledger()
        led.reserve({ResourceKind.TOKENS: 300})
        assert led.available(ResourceKind.TOKENS) == 700

    def test_multiple_reservations(self) -> None:
        led = _ledger()
        r1 = led.reserve({ResourceKind.TOKENS: 300})
        r2 = led.reserve({ResourceKind.TOKENS: 400})
        assert r1.id != r2.id
        assert led.available(ResourceKind.TOKENS) == 300


class TestConsume:
    def test_actual_equals_reserved(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        out = led.consume(r.id, {ResourceKind.TOKENS: 100})
        assert out.overrun is False
        assert led.get(r.id).status is ReservationStatus.CONSUMED

    def test_actual_less_than_reserved(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        out = led.consume(r.id, {ResourceKind.TOKENS: 80})
        assert out.overrun is False
        assert led.available(ResourceKind.TOKENS) == 920

    def test_actual_more_than_reserved(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        out = led.consume(r.id, {ResourceKind.TOKENS: 120})
        assert out.overrun is True
        assert out.excess[ResourceKind.TOKENS] == 20
        assert led.available(ResourceKind.TOKENS) == 880

    def test_actual_not_lost(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        led.consume(r.id, {ResourceKind.TOKENS: 120})
        consumed = led.get(r.id)
        assert consumed.consumed_amounts is not None
        assert consumed.consumed_amounts[ResourceKind.TOKENS] == 120

    def test_consume_released_fails(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        led.release(r.id)
        with pytest.raises(EnergyReservationError):
            led.consume(r.id, {ResourceKind.TOKENS: 80})

    def test_repeated_consume_fails(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        led.consume(r.id, {ResourceKind.TOKENS: 80})
        with pytest.raises(EnergyReservationError):
            led.consume(r.id, {ResourceKind.TOKENS: 80})

    def test_unknown_reservation_fails(self) -> None:
        led = _ledger()
        with pytest.raises(EnergyReservationError):
            led.consume("nonexistent", {ResourceKind.TOKENS: 10})

    def test_negative_actual_rejected(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        with pytest.raises(InvariantViolation):
            led.consume(r.id, {ResourceKind.TOKENS: -1})

    def test_negative_actual_multi_resource_atomic(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100, ResourceKind.API_CALLS: 5})
        avail_before = led.available(ResourceKind.TOKENS)
        with pytest.raises(InvariantViolation):
            led.consume(r.id, {ResourceKind.TOKENS: 80, ResourceKind.API_CALLS: -1})
        assert led.get(r.id).status is ReservationStatus.RESERVED
        assert led.available(ResourceKind.TOKENS) == avail_before

    def test_overrun_blocks_further_reservation(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 1000})
        led.consume(r.id, {ResourceKind.TOKENS: 1020})
        with pytest.raises(EnergyBudgetExceededError):
            led.reserve({ResourceKind.TOKENS: 1})


class TestRelease:
    def test_release_reserved(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 300})
        released = led.release(r.id)
        assert released.status is ReservationStatus.RELEASED
        assert led.available(ResourceKind.TOKENS) == 1000

    def test_double_release_fails(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        led.release(r.id)
        with pytest.raises(EnergyReservationError):
            led.release(r.id)

    def test_release_consumed_fails(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        led.consume(r.id, {ResourceKind.TOKENS: 80})
        with pytest.raises(EnergyReservationError):
            led.release(r.id)

    def test_release_unknown_fails(self) -> None:
        led = _ledger()
        with pytest.raises(EnergyReservationError):
            led.release("nope")

    def test_release_does_not_exceed_original(self) -> None:
        led = _ledger()
        led.reserve({ResourceKind.TOKENS: 300})
        r2 = led.reserve({ResourceKind.TOKENS: 200})
        led.release(r2.id)
        assert led.available(ResourceKind.TOKENS) == 700


class TestLifecycle:
    def test_lookup(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        found = led.get(r.id)
        assert found.id == r.id

    def test_unknown_lookup_fails(self) -> None:
        led = _ledger()
        with pytest.raises(EnergyReservationError):
            led.get("ghost")

    def test_independent_reservations(self) -> None:
        led = _ledger()
        r1 = led.reserve({ResourceKind.TOKENS: 100})
        r2 = led.reserve({ResourceKind.TOKENS: 200})
        led.consume(r1.id, {ResourceKind.TOKENS: 90})
        led.release(r2.id)
        assert led.get(r1.id).status is ReservationStatus.CONSUMED
        assert led.get(r2.id).status is ReservationStatus.RELEASED
        assert led.available(ResourceKind.TOKENS) == 910

    def test_fresh_ledger_state(self) -> None:
        led1 = _ledger()
        led1.reserve({ResourceKind.TOKENS: 500})
        led2 = _ledger()
        assert led2.available(ResourceKind.TOKENS) == 1000

    def test_reservation_immutable(self) -> None:
        led = _ledger()
        r = led.reserve({ResourceKind.TOKENS: 100})
        with pytest.raises(AttributeError):
            r.status = ReservationStatus.CONSUMED  # type: ignore[misc]

    def test_counters_never_negative(self) -> None:
        b = EnergyBudget({ResourceKind.TOKENS: 100})
        led = _ledger(b)
        r = led.reserve({ResourceKind.TOKENS: 50})
        led.release(r.id)
        assert led.available(ResourceKind.TOKENS) == 100
