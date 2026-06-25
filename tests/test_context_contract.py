"""CP5 context contract tests: consumer, artifact request, budget, build request."""

from __future__ import annotations

import pytest

from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
    ContextError,
)
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TaskId
from ant_orchestrator.errors import AntError


class TestConsumerKind:
    def test_all_kinds_serialize(self) -> None:
        for kind in ConsumerKind:
            assert isinstance(kind.value, str)
            assert kind.value

    def test_worker_value(self) -> None:
        assert ConsumerKind.WORKER.value == "worker"


class TestContextConsumer:
    def test_valid_consumer(self) -> None:
        c = ContextConsumer(ConsumerKind.WORKER, "test-worker-1")
        assert c.kind is ConsumerKind.WORKER
        assert c.value == "test-worker-1"

    def test_empty_value_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextConsumer(ConsumerKind.PLANNER, "")

    def test_whitespace_only_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextConsumer(ConsumerKind.PLANNER, "   ")

    def test_tab_only_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextConsumer(ConsumerKind.PLANNER, "\t\n")

    def test_max_length_exceeded(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextConsumer(ConsumerKind.WORKER, "x" * 257)

    def test_max_length_exact_allowed(self) -> None:
        c = ContextConsumer(ConsumerKind.WORKER, "x" * 256)
        assert len(c.value) == 256

    def test_frozen(self) -> None:
        c = ContextConsumer(ConsumerKind.WORKER, "w")
        with pytest.raises(AttributeError):
            c.value = "other"  # type: ignore[misc]

    def test_consumer_is_not_task_identity(self) -> None:
        c = ContextConsumer(ConsumerKind.WORKER, "w1")
        t = TaskId("TASK-001")
        assert c.value != t.value

    def test_no_worker_entity_required(self) -> None:
        c = ContextConsumer(ConsumerKind.CAPABILITY, "code_review")
        assert c.kind is ConsumerKind.CAPABILITY


class TestArtifactRequest:
    def test_valid_request(self) -> None:
        r = ArtifactRequest("src/main.py", ArtifactRequirement.REQUIRED)
        assert r.path == "src/main.py"
        assert r.requirement is ArtifactRequirement.REQUIRED

    def test_empty_path_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ArtifactRequest("", ArtifactRequirement.OPTIONAL)

    def test_frozen(self) -> None:
        r = ArtifactRequest("f.py", ArtifactRequirement.OPTIONAL)
        with pytest.raises(AttributeError):
            r.path = "other.py"  # type: ignore[misc]

    def test_requirement_serialization(self) -> None:
        assert ArtifactRequirement.REQUIRED.value == "required"
        assert ArtifactRequirement.OPTIONAL.value == "optional"


class TestContextBudget:
    def test_valid_budget(self) -> None:
        b = ContextBudget(max_input_tokens=12000, max_files=8, max_file_tokens=3000)
        assert b.max_input_tokens == 12000
        assert b.max_files == 8
        assert b.max_file_tokens == 3000
        assert b.allow_full_file is False

    def test_allow_full_file(self) -> None:
        b = ContextBudget(12000, 8, 3000, allow_full_file=True)
        assert b.allow_full_file is True

    def test_zero_tokens_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextBudget(0, 8, 3000)

    def test_negative_tokens_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextBudget(-1, 8, 3000)

    def test_zero_files_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextBudget(12000, 0, 3000)

    def test_zero_file_tokens_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextBudget(12000, 8, 0)

    def test_per_file_exceeds_total_rejected(self) -> None:
        with pytest.raises(InvariantViolation):
            ContextBudget(max_input_tokens=100, max_files=8, max_file_tokens=200)

    def test_per_file_equals_total_allowed(self) -> None:
        b = ContextBudget(max_input_tokens=3000, max_files=1, max_file_tokens=3000)
        assert b.max_file_tokens == b.max_input_tokens

    def test_frozen(self) -> None:
        b = ContextBudget(12000, 8, 3000)
        with pytest.raises(AttributeError):
            b.max_input_tokens = 0  # type: ignore[misc]

    def test_no_mutable_default(self) -> None:
        b1 = ContextBudget(1000, 5, 500)
        b2 = ContextBudget(1000, 5, 500)
        assert b1 == b2


class TestContextBuildRequest:
    def test_valid_request(self) -> None:
        r = ContextBuildRequest(
            task_id=TaskId("TASK-001"),
            consumer=ContextConsumer(ConsumerKind.WORKER, "w1"),
            requests=(ArtifactRequest("f.py", ArtifactRequirement.REQUIRED),),
            excluded=("secret.env",),
            budget=ContextBudget(12000, 8, 3000),
        )
        assert r.task_id.value == "TASK-001"
        assert len(r.requests) == 1
        assert len(r.excluded) == 1

    def test_empty_requests_valid(self) -> None:
        r = ContextBuildRequest(
            task_id=TaskId("T-1"),
            consumer=ContextConsumer(ConsumerKind.PLANNER, "plan"),
            requests=(),
            excluded=(),
            budget=ContextBudget(1000, 1, 1000),
        )
        assert r.requests == ()

    def test_tuples_immutable(self) -> None:
        r = ContextBuildRequest(
            task_id=TaskId("T-1"),
            consumer=ContextConsumer(ConsumerKind.WORKER, "w"),
            requests=(),
            excluded=(),
            budget=ContextBudget(1000, 1, 1000),
        )
        with pytest.raises((TypeError, AttributeError)):
            r.requests += (ArtifactRequest("x.py", ArtifactRequirement.OPTIONAL),)  # type: ignore[assignment]


class TestContextErrorTaxonomy:
    def test_context_error_is_ant_error(self) -> None:
        assert issubclass(ContextError, AntError)

    def test_budget_exceeded_is_context_error(self) -> None:
        from ant_orchestrator.application.ports.context_builder import (
            ContextBudgetExceededError,
        )

        assert issubclass(ContextBudgetExceededError, ContextError)

    def test_scope_violation_is_context_error(self) -> None:
        from ant_orchestrator.application.ports.context_builder import (
            ContextScopeViolation,
        )

        assert issubclass(ContextScopeViolation, ContextError)
