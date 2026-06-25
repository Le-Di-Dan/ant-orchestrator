"""CP8 approval request contract tests."""

from __future__ import annotations

from datetime import UTC, datetime

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    ApprovalConsequence,
    ApprovalReason,
    ContextDisposition,
    EnergyBudget,
    EnergyDecision,
    ResourceKind,
)
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from tests.test_energy_manager import _FakeAction, _make_manager, _plan

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_TASK = TaskId("task-1")
_CID = CorrelationId("corr-1")
_BUDGET = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 10})


class TestCloudApproval:
    def test_cloud_route_creates_approval(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan, model_action=_FakeAction())
        assert result.approval_request is not None
        ar = result.approval_request
        assert ar.reason is ApprovalReason.CLOUD_REQUIRES_APPROVAL
        assert ar.proposed_route is EnergyDecision.ESCALATE_CLOUD

    def test_cloud_approval_has_identity(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan, model_action=_FakeAction())
        ar = result.approval_request
        assert ar is not None
        assert ar.task_id.value == "task-1"
        assert ar.correlation_id.value == "corr-1"
        assert ar.action_kind is ActionKind.LOCAL_LLM_INFERENCE

    def test_cloud_approval_no_prompt_no_secret(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan, model_action=_FakeAction())
        ar = result.approval_request
        assert ar is not None
        # ApprovalRequest must not contain string-valued fields with raw prompts
        assert not hasattr(ar, "prompt")
        assert not hasattr(ar, "output")
        assert not hasattr(ar, "secret")

    def test_cloud_approval_immutable(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan, model_action=_FakeAction())
        ar = result.approval_request
        assert ar is not None
        try:
            ar.reason = ApprovalReason.BUDGET_INSUFFICIENT  # type: ignore[misc]
            raise AssertionError("should be frozen")
        except (AttributeError, TypeError):
            pass


class TestContextBudgetApproval:
    def test_context_budget_creates_approval(self) -> None:
        mgr, _, _ = _make_manager()
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=True, required_security_failure=False
        )
        result = mgr.execute(_plan(ctx=ctx), model_action=_FakeAction())
        ar = result.approval_request
        assert ar is not None
        assert ar.reason is ApprovalReason.CONTEXT_BUDGET_EXCEEDED

    def test_security_failure_no_budget_approval(self) -> None:
        mgr, _, _ = _make_manager()
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=False, required_security_failure=True
        )
        result = mgr.execute(_plan(ctx=ctx), model_action=_FakeAction())
        assert result.decision is EnergyDecision.REJECT
        assert result.approval_request is None

    def test_scope_failure_no_cloud_approval(self) -> None:
        mgr, _, _ = _make_manager()
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=False, required_security_failure=True
        )
        result = mgr.execute(_plan(ctx=ctx, cloud_avail=True), model_action=_FakeAction())
        assert result.decision is EnergyDecision.REJECT
        # No cloud approval for security/scope failures
        if result.approval_request is not None:
            assert result.approval_request.reason is not ApprovalReason.CLOUD_REQUIRES_APPROVAL


class TestOverrunApproval:
    def test_overrun_creates_approval(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 200})
        plan = _plan(estimated={ResourceKind.TOKENS: 100})
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.STOP
        ar = result.approval_request
        assert ar is not None
        assert ar.reason is ApprovalReason.RUNTIME_BUDGET_EXCEEDED

    def test_overrun_approval_has_excess(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 150})
        plan = _plan(estimated={ResourceKind.TOKENS: 100})
        result = mgr.execute(plan, model_action=model)
        ar = result.approval_request
        assert ar is not None
        # required_additional should show the excess
        excess = ar.required_additional.get(ResourceKind.TOKENS, 0)
        assert excess == 50

    def test_overrun_approval_preserves_identity(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 200})
        plan = _plan(estimated={ResourceKind.TOKENS: 100})
        result = mgr.execute(plan, model_action=model)
        ar = result.approval_request
        assert ar is not None
        assert ar.task_id.value == "task-1"
        assert ar.correlation_id.value == "corr-1"


class TestApprovalContract:
    def test_approval_has_current_budget(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan)
        ar = result.approval_request
        assert ar is not None
        assert isinstance(ar.current_budget, EnergyBudget)

    def test_approval_has_consequence(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan)
        ar = result.approval_request
        assert ar is not None
        assert isinstance(ar.consequence_if_denied, ApprovalConsequence)

    def test_approval_has_timestamp(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan)
        ar = result.approval_request
        assert ar is not None
        assert isinstance(ar.created_at, UtcTimestamp)

    def test_approval_no_resolve_no_resume(self) -> None:
        mgr, _, _ = _make_manager()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan)
        ar = result.approval_request
        assert ar is not None
        assert not hasattr(ar, "resolve")
        assert not hasattr(ar, "resume")
        assert not hasattr(ar, "approve")
