"""CP5 token estimator tests: strategy, determinism, edge cases, injection."""

from __future__ import annotations

import pytest

from ant_orchestrator.context.estimator import (
    CharacterHeuristicEstimator,
    TokenEstimationStrategy,
    TokenEstimator,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


class TestCharacterHeuristic:
    def test_empty_text(self) -> None:
        e = CharacterHeuristicEstimator()
        assert e.estimate("") == TokenCount(0)

    def test_one_character(self) -> None:
        e = CharacterHeuristicEstimator()
        assert e.estimate("x") == TokenCount(1)

    def test_exact_divisor(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        assert e.estimate("abcd") == TokenCount(1)

    def test_divisor_plus_one(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        assert e.estimate("abcde") == TokenCount(2)

    def test_unicode_code_points(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        r = e.estimate("日本語テ")
        assert r == TokenCount(1)

    def test_emoji(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        r = e.estimate("🎉🎊🎈🎁")
        assert r == TokenCount(1)

    def test_multiline(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        text = "line1\nline2\nline3\n"
        assert e.estimate(text).value > 0

    def test_custom_divisor(self) -> None:
        e = CharacterHeuristicEstimator(divisor=2)
        assert e.estimate("abcde") == TokenCount(3)

    def test_divisor_one(self) -> None:
        e = CharacterHeuristicEstimator(divisor=1)
        assert e.estimate("hello") == TokenCount(5)

    def test_invalid_divisor_zero(self) -> None:
        with pytest.raises(InvariantViolation):
            CharacterHeuristicEstimator(divisor=0)

    def test_invalid_divisor_negative(self) -> None:
        with pytest.raises(InvariantViolation):
            CharacterHeuristicEstimator(divisor=-1)

    def test_deterministic(self) -> None:
        e = CharacterHeuristicEstimator()
        text = "the quick brown fox jumps over the lazy dog"
        r1 = e.estimate(text)
        r2 = e.estimate(text)
        assert r1 == r2

    def test_large_text(self) -> None:
        e = CharacterHeuristicEstimator(divisor=4)
        text = "x" * 10000
        assert e.estimate(text) == TokenCount(2500)


class TestStrategyAndVersion:
    def test_strategy_is_character_heuristic(self) -> None:
        e = CharacterHeuristicEstimator()
        assert e.strategy is TokenEstimationStrategy.CHARACTER_HEURISTIC

    def test_version_positive(self) -> None:
        e = CharacterHeuristicEstimator()
        assert e.version > 0

    def test_strategy_serialization(self) -> None:
        assert TokenEstimationStrategy.CHARACTER_HEURISTIC.value == "character_heuristic"


class TestProtocolConformance:
    def test_satisfies_protocol(self) -> None:
        e = CharacterHeuristicEstimator()
        assert isinstance(e, TokenEstimator)

    def test_fake_estimator_injection(self) -> None:
        class _FakeEstimator:
            @property
            def strategy(self) -> TokenEstimationStrategy:
                return TokenEstimationStrategy.CHARACTER_HEURISTIC

            @property
            def version(self) -> int:
                return 99

            def estimate(self, text: str) -> TokenCount:
                return TokenCount(42)

        fake = _FakeEstimator()
        assert isinstance(fake, TokenEstimator)
        assert fake.estimate("anything") == TokenCount(42)
        assert fake.version == 99
