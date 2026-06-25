"""Token estimation — injectable strategy for context budget (CP5).

Provides the ``TokenEstimator`` protocol and a character-heuristic MVP
implementation. No provider SDK, no network, no file I/O.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Protocol, runtime_checkable

from ant_orchestrator.config.constants import TOKEN_ESTIMATION_DEFAULT_DIVISOR
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


class TokenEstimationStrategy(Enum):
    """Named strategy for token estimation (logged in manifest)."""

    CHARACTER_HEURISTIC = "character_heuristic"


@runtime_checkable
class TokenEstimator(Protocol):
    """Estimates token count from text. Injectable; strategy and version logged."""

    @property
    def strategy(self) -> TokenEstimationStrategy: ...

    @property
    def version(self) -> int: ...

    def estimate(self, text: str) -> TokenCount: ...


class CharacterHeuristicEstimator:
    """``ceil(len(text) / divisor)`` estimation. ``len`` counts Unicode code points."""

    def __init__(self, divisor: int = TOKEN_ESTIMATION_DEFAULT_DIVISOR) -> None:
        if divisor <= 0:
            raise InvariantViolation("CharacterHeuristicEstimator.divisor must be > 0")
        self._divisor = divisor

    @property
    def strategy(self) -> TokenEstimationStrategy:
        return TokenEstimationStrategy.CHARACTER_HEURISTIC

    @property
    def version(self) -> int:
        return 1

    def estimate(self, text: str) -> TokenCount:
        if not text:
            return TokenCount(0)
        return TokenCount(math.ceil(len(text) / self._divisor))
