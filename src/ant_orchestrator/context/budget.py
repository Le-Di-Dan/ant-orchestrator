"""Context budget tracking — pure arithmetic for selection (CP5).

Tracks tokens and file counts consumed during selection. Never mutates
the ``ContextBudget`` constraint; tracking state is internal.
"""

from __future__ import annotations

from dataclasses import dataclass

from ant_orchestrator.application.ports.context_builder import ContextBudget
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount


@dataclass(frozen=True, slots=True)
class BudgetUsage:
    """Snapshot of tokens and files consumed or remaining."""

    tokens: int
    files: int

    def __post_init__(self) -> None:
        if self.tokens < 0:
            raise InvariantViolation("BudgetUsage.tokens must be >= 0")
        if self.files < 0:
            raise InvariantViolation("BudgetUsage.files must be >= 0")


class BudgetTracker:
    """Mutable tracker for budget consumption during selection."""

    def __init__(self, budget: ContextBudget) -> None:
        self._budget = budget
        self._tokens_used = 0
        self._files_used = 0

    @property
    def usage(self) -> BudgetUsage:
        return BudgetUsage(tokens=self._tokens_used, files=self._files_used)

    def can_fit(self, tokens: TokenCount) -> bool:
        if tokens.value > self._budget.max_file_tokens:
            return False
        if self._files_used >= self._budget.max_files:
            return False
        if self._tokens_used + tokens.value > self._budget.max_input_tokens:
            return False
        return True

    def consume(self, tokens: TokenCount) -> None:
        if not self.can_fit(tokens):
            raise InvariantViolation("Cannot consume: budget exceeded")
        self._tokens_used += tokens.value
        self._files_used += 1

    def remaining(self) -> BudgetUsage:
        return BudgetUsage(
            tokens=max(0, self._budget.max_input_tokens - self._tokens_used),
            files=max(0, self._budget.max_files - self._files_used),
        )
