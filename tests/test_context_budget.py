"""CP5 context budget tests: tracker, usage, boundary, arithmetic."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.context_builder import ContextBudget
from ant_orchestrator.context.budget import BudgetTracker, BudgetUsage
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount

_BUDGET = ContextBudget(max_input_tokens=1000, max_files=3, max_file_tokens=500)


class TestBudgetUsage:
    def test_valid_usage(self) -> None:
        u = BudgetUsage(tokens=100, files=2)
        assert u.tokens == 100
        assert u.files == 2

    def test_zero_usage(self) -> None:
        u = BudgetUsage(tokens=0, files=0)
        assert u.tokens == 0

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            BudgetUsage(tokens=-1, files=0)

    def test_negative_files_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            BudgetUsage(tokens=0, files=-1)

    def test_frozen(self) -> None:
        u = BudgetUsage(0, 0)
        with pytest.raises(AttributeError):
            u.tokens = 1  # type: ignore[misc]


class TestBudgetTracker:
    def test_initial_usage_zero(self) -> None:
        t = BudgetTracker(_BUDGET)
        assert t.usage == BudgetUsage(0, 0)

    def test_can_fit_within_budget(self) -> None:
        t = BudgetTracker(_BUDGET)
        assert t.can_fit(TokenCount(100)) is True

    def test_consume_updates_usage(self) -> None:
        t = BudgetTracker(_BUDGET)
        t.consume(TokenCount(100))
        assert t.usage == BudgetUsage(tokens=100, files=1)

    def test_remaining_after_consume(self) -> None:
        t = BudgetTracker(_BUDGET)
        t.consume(TokenCount(300))
        r = t.remaining()
        assert r.tokens == 700
        assert r.files == 2

    def test_exact_total_boundary_fits(self) -> None:
        t = BudgetTracker(ContextBudget(100, 3, 100))
        assert t.can_fit(TokenCount(100)) is True

    def test_total_boundary_plus_one_rejected(self) -> None:
        t = BudgetTracker(ContextBudget(100, 3, 100))
        t.consume(TokenCount(50))
        assert t.can_fit(TokenCount(51)) is False

    def test_exact_file_count_fits(self) -> None:
        t = BudgetTracker(ContextBudget(1000, 2, 500))
        t.consume(TokenCount(10))
        assert t.can_fit(TokenCount(10)) is True

    def test_file_count_plus_one_rejected(self) -> None:
        t = BudgetTracker(ContextBudget(1000, 2, 500))
        t.consume(TokenCount(10))
        t.consume(TokenCount(10))
        assert t.can_fit(TokenCount(10)) is False

    def test_exact_per_file_boundary_fits(self) -> None:
        t = BudgetTracker(ContextBudget(1000, 3, 500))
        assert t.can_fit(TokenCount(500)) is True

    def test_per_file_boundary_plus_one_rejected(self) -> None:
        t = BudgetTracker(ContextBudget(1000, 3, 500))
        assert t.can_fit(TokenCount(501)) is False

    def test_per_file_enforced_before_total(self) -> None:
        t = BudgetTracker(ContextBudget(10000, 10, 100))
        assert t.can_fit(TokenCount(101)) is False

    def test_consume_exceeding_raises(self) -> None:
        t = BudgetTracker(ContextBudget(100, 1, 100))
        t.consume(TokenCount(100))
        with pytest.raises(InvariantViolation):
            t.consume(TokenCount(1))

    def test_remaining_never_negative(self) -> None:
        t = BudgetTracker(ContextBudget(100, 1, 100))
        t.consume(TokenCount(100))
        r = t.remaining()
        assert r.tokens == 0
        assert r.files == 0

    def test_zero_token_file(self) -> None:
        t = BudgetTracker(_BUDGET)
        assert t.can_fit(TokenCount(0)) is True
        t.consume(TokenCount(0))
        assert t.usage == BudgetUsage(tokens=0, files=1)

    def test_budget_not_mutated(self) -> None:
        b = ContextBudget(1000, 3, 500)
        t = BudgetTracker(b)
        t.consume(TokenCount(200))
        assert b.max_input_tokens == 1000
