"""CP5 context selection tests: ordering, budget, dedup, exclusion, no-fallback."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ContextBudget,
)
from ant_orchestrator.context.selection import (
    ArtifactCandidate,
    ContextSelectionResult,
    ContextSelector,
    RejectionReason,
    SelectionReason,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount

_BUDGET = ContextBudget(max_input_tokens=1000, max_files=5, max_file_tokens=500)


def _cand(
    path: str,
    req: ArtifactRequirement = ArtifactRequirement.OPTIONAL,
    tokens: int = 100,
    eligible: bool = True,
    rejection: RejectionReason | None = None,
    order: int = 0,
) -> ArtifactCandidate:
    return ArtifactCandidate(
        request=ArtifactRequest(path, req),
        estimated_tokens=TokenCount(tokens),
        eligible=eligible,
        rejection_reason=rejection,
        original_order=order,
    )


def _select(
    candidates: tuple[ArtifactCandidate, ...],
    excluded: frozenset[str] = frozenset(),
    budget: ContextBudget = _BUDGET,
) -> ContextSelectionResult:
    return ContextSelector().select(candidates, excluded, budget)


class TestOrdering:
    def test_required_selected_before_optional(self) -> None:
        r = _select(
            (
                _cand("opt.py", ArtifactRequirement.OPTIONAL, order=0),
                _cand("req.py", ArtifactRequirement.REQUIRED, order=1),
            )
        )
        assert r.selected[0].path == "req.py"
        assert r.selected[1].path == "opt.py"

    def test_stable_order_within_same_requirement(self) -> None:
        r = _select(
            (
                _cand("a.py", ArtifactRequirement.OPTIONAL, order=0),
                _cand("b.py", ArtifactRequirement.OPTIONAL, order=1),
                _cand("c.py", ArtifactRequirement.OPTIONAL, order=2),
            )
        )
        paths = [s.path for s in r.selected]
        assert paths == ["a.py", "b.py", "c.py"]

    def test_selection_reason_matches_requirement(self) -> None:
        r = _select(
            (
                _cand("r.py", ArtifactRequirement.REQUIRED, order=0),
                _cand("o.py", ArtifactRequirement.OPTIONAL, order=1),
            )
        )
        assert r.selected[0].reason is SelectionReason.REQUESTED_REQUIRED
        assert r.selected[1].reason is SelectionReason.REQUESTED_OPTIONAL


class TestEligibility:
    def test_outside_scope_rejected(self) -> None:
        r = _select((_cand("x.py", eligible=False, rejection=RejectionReason.OUTSIDE_SCOPE),))
        assert len(r.rejected) == 1
        assert r.rejected[0].reason is RejectionReason.OUTSIDE_SCOPE

    def test_binary_rejected(self) -> None:
        r = _select((_cand("b.bin", eligible=False, rejection=RejectionReason.BINARY),))
        assert r.rejected[0].reason is RejectionReason.BINARY

    def test_secret_file_rejected(self) -> None:
        r = _select((_cand(".env", eligible=False, rejection=RejectionReason.SECRET_FILE),))
        assert r.rejected[0].reason is RejectionReason.SECRET_FILE

    def test_oversized_rejected(self) -> None:
        r = _select((_cand("big.py", eligible=False, rejection=RejectionReason.OVERSIZED),))
        assert r.rejected[0].reason is RejectionReason.OVERSIZED

    def test_required_ineligible_sets_required_failure(self) -> None:
        r = _select(
            (
                _cand(
                    "r.py",
                    ArtifactRequirement.REQUIRED,
                    eligible=False,
                    rejection=RejectionReason.OUTSIDE_SCOPE,
                ),
            )
        )
        assert r.required_failure is True


class TestExclusion:
    def test_excluded_optional_rejected(self) -> None:
        r = _select(
            (_cand("f.py", order=0),),
            excluded=frozenset({"f.py"}),
        )
        assert len(r.rejected) == 1
        assert r.rejected[0].reason is RejectionReason.EXCLUDED
        assert r.required_failure is False

    def test_excluded_required_sets_failure(self) -> None:
        r = _select(
            (_cand("f.py", ArtifactRequirement.REQUIRED, order=0),),
            excluded=frozenset({"f.py"}),
        )
        assert r.rejected[0].reason is RejectionReason.EXCLUDED
        assert r.required_failure is True


class TestBudgetBoundaries:
    def test_exact_total_budget_selected(self) -> None:
        b = ContextBudget(100, 5, 100)
        r = _select((_cand("f.py", tokens=100),), budget=b)
        assert len(r.selected) == 1

    def test_total_budget_plus_one_rejected(self) -> None:
        b = ContextBudget(100, 5, 100)
        r = _select(
            (
                _cand("a.py", tokens=50, order=0),
                _cand("b.py", tokens=51, order=1),
            ),
            budget=b,
        )
        assert len(r.selected) == 1
        assert r.rejected[0].reason is RejectionReason.BUDGET_EXCEEDED

    def test_exact_file_count_selected(self) -> None:
        b = ContextBudget(10000, 2, 5000)
        r = _select(
            (
                _cand("a.py", tokens=10, order=0),
                _cand("b.py", tokens=10, order=1),
            ),
            budget=b,
        )
        assert len(r.selected) == 2

    def test_file_count_plus_one_rejected(self) -> None:
        b = ContextBudget(10000, 2, 5000)
        r = _select(
            (
                _cand("a.py", tokens=10, order=0),
                _cand("b.py", tokens=10, order=1),
                _cand("c.py", tokens=10, order=2),
            ),
            budget=b,
        )
        assert len(r.selected) == 2
        assert r.rejected[0].reason is RejectionReason.BUDGET_EXCEEDED

    def test_exact_per_file_selected(self) -> None:
        b = ContextBudget(10000, 5, 100)
        r = _select((_cand("f.py", tokens=100),), budget=b)
        assert len(r.selected) == 1

    def test_per_file_plus_one_rejected(self) -> None:
        b = ContextBudget(10000, 5, 100)
        r = _select((_cand("f.py", tokens=101),), budget=b)
        assert len(r.rejected) == 1
        assert r.rejected[0].reason is RejectionReason.BUDGET_EXCEEDED

    def test_required_budget_failure(self) -> None:
        b = ContextBudget(50, 5, 50)
        r = _select((_cand("f.py", ArtifactRequirement.REQUIRED, tokens=51),), budget=b)
        assert r.required_failure is True
        assert r.rejected[0].reason is RejectionReason.BUDGET_EXCEEDED

    def test_optional_budget_rejected_continues(self) -> None:
        b = ContextBudget(250, 5, 200)
        r = _select(
            (
                _cand("big.py", tokens=150, order=0),
                _cand("small.py", tokens=60, order=1),
            ),
            budget=b,
        )
        assert len(r.selected) == 2

    def test_optional_skip_large_select_small(self) -> None:
        b = ContextBudget(100, 5, 100)
        r = _select(
            (
                _cand("big.py", tokens=80, order=0),
                _cand("huge.py", tokens=80, order=1),
                _cand("small.py", tokens=20, order=2),
            ),
            budget=b,
        )
        selected_paths = {s.path for s in r.selected}
        assert "big.py" in selected_paths
        assert "small.py" in selected_paths
        assert "huge.py" not in selected_paths


class TestBudgetArithmetic:
    def test_usage_reflects_selected(self) -> None:
        r = _select(
            (
                _cand("a.py", tokens=100, order=0),
                _cand("b.py", tokens=200, order=1),
            )
        )
        assert r.budget_used.tokens == 300
        assert r.budget_used.files == 2

    def test_remaining_correct(self) -> None:
        r = _select(
            (_cand("a.py", tokens=300),),
            budget=ContextBudget(1000, 5, 500),
        )
        assert r.budget_remaining.tokens == 700
        assert r.budget_remaining.files == 4

    def test_initial_budget_preserved(self) -> None:
        b = ContextBudget(1000, 5, 500)
        r = _select((_cand("a.py", tokens=100),), budget=b)
        assert r.budget_initial is b


class TestDuplicates:
    def test_duplicate_optional_deduped(self) -> None:
        r = _select(
            (
                _cand("f.py", ArtifactRequirement.OPTIONAL, tokens=100, order=0),
                _cand("f.py", ArtifactRequirement.OPTIONAL, tokens=100, order=1),
            )
        )
        assert len(r.selected) == 1
        assert r.budget_used.files == 1

    def test_duplicate_required_deduped(self) -> None:
        r = _select(
            (
                _cand("f.py", ArtifactRequirement.REQUIRED, tokens=50, order=0),
                _cand("f.py", ArtifactRequirement.REQUIRED, tokens=50, order=1),
            )
        )
        assert len(r.selected) == 1

    def test_required_dominates_optional(self) -> None:
        r = _select(
            (
                _cand("f.py", ArtifactRequirement.OPTIONAL, tokens=100, order=0),
                _cand("f.py", ArtifactRequirement.REQUIRED, tokens=100, order=1),
            )
        )
        assert len(r.selected) == 1
        assert r.selected[0].reason is SelectionReason.REQUESTED_REQUIRED

    def test_no_double_counting(self) -> None:
        r = _select(
            (
                _cand("f.py", tokens=100, order=0),
                _cand("f.py", tokens=100, order=1),
                _cand("g.py", tokens=100, order=2),
            )
        )
        assert r.budget_used.tokens == 200
        assert r.budget_used.files == 2


class TestCompleteness:
    def test_every_candidate_selected_or_rejected(self) -> None:
        r = _select(
            (
                _cand("a.py", tokens=100, order=0),
                _cand("b.py", eligible=False, rejection=RejectionReason.BINARY, order=1),
            )
        )
        total = len(r.selected) + len(r.rejected)
        assert total == 2

    def test_deterministic_repeated_runs(self) -> None:
        cands = (
            _cand("c.py", tokens=100, order=2),
            _cand("a.py", ArtifactRequirement.REQUIRED, tokens=50, order=0),
            _cand("b.py", tokens=80, order=1),
        )
        r1 = _select(cands)
        r2 = _select(cands)
        assert r1.selected == r2.selected
        assert r1.rejected == r2.rejected

    def test_input_not_mutated(self) -> None:
        cands = (
            _cand("a.py", tokens=100, order=0),
            _cand("b.py", tokens=200, order=1),
        )
        _select(cands)
        assert len(cands) == 2
        assert cands[0].request.path == "a.py"


class TestNoRepositoryFallback:
    def test_empty_candidates_no_discovery(self) -> None:
        r = _select(())
        assert r.selected == ()
        assert r.rejected == ()
        assert r.required_failure is False

    def test_output_only_from_explicit_input(self) -> None:
        r = _select((_cand("explicit.py", tokens=10),))
        all_paths = {s.path for s in r.selected} | {j.path for j in r.rejected}
        assert all_paths == {"explicit.py"}


class TestCandidateInvariants:
    def test_eligible_with_reason_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            _cand("f.py", eligible=True, rejection=RejectionReason.BINARY)

    def test_ineligible_without_reason_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            _cand("f.py", eligible=False, rejection=None)

    def test_negative_order_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            _cand("f.py", order=-1)
