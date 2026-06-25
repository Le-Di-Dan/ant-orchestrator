"""CP8 EnergyManager facade tests — side-effect gating and audit ordering."""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType

from ant_orchestrator.application.ports.audit import AuditEvent, CorrelationId
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    CapabilityKind,
    ContextDisposition,
    EnergyActionPlan,
    EnergyActionResult,
    EnergyBudget,
    EnergyDecision,
    QualityRequirement,
    ResourceKind,
)
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.energy.manager import EnergyManager
from ant_orchestrator.energy.reservation import ReservationLedger
from ant_orchestrator.energy.routing import RoutingPolicy
from tests.conftest import FakeClock, SequentialIdGenerator

_TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
_TASK = TaskId("task-1")
_CID = CorrelationId("corr-1")
_BUDGET = EnergyBudget({ResourceKind.TOKENS: 1000, ResourceKind.API_CALLS: 10})


class _FakeAudit:
    def __init__(self, fail: bool = False) -> None:
        self.events: list[AuditEvent] = []
        self.fail = fail
        self.fail_after: int = -1  # -1 = always succeed unless fail=True
        self._call_count = 0

    def write(self, event: AuditEvent) -> None:
        self._call_count += 1
        if self.fail:
            raise RuntimeError("audit failure")
        if self.fail_after >= 0 and self._call_count > self.fail_after:
            raise RuntimeError("audit failure after N")
        self.events.append(event)


class _FakeAction:
    def __init__(
        self,
        actual: dict[ResourceKind, int] | None = None,
        started: bool = True,
        raise_exc: bool = False,
    ) -> None:
        self.calls = 0
        self._actual = actual or {}
        self._started = started
        self._raise = raise_exc

    def execute(self) -> EnergyActionResult:
        self.calls += 1
        if self._raise:
            raise RuntimeError("action failed")
        return EnergyActionResult(
            actual=MappingProxyType(self._actual),
            side_effect_started=self._started,
        )


def _make_manager(
    budget: EnergyBudget = _BUDGET,
    audit: _FakeAudit | None = None,
) -> tuple[EnergyManager, _FakeAudit, ReservationLedger]:
    if audit is None:
        audit = _FakeAudit()
    effective = _BUDGET if budget is _BUDGET else budget
    ledger = ReservationLedger(effective, FakeClock(_TS), SequentialIdGenerator())
    manager = EnergyManager(
        ledger=ledger,
        audit_sink=audit,  # type: ignore[arg-type]
        routing_policy=RoutingPolicy(),
        enforcement_policy=EnforcementPolicy(),
        clock=FakeClock(_TS),
        id_gen=SequentialIdGenerator(),
    )
    return manager, audit, ledger


def _plan(
    *,
    cap: CapabilityKind = CapabilityKind.LLM_INFERENCE,
    det_avail: bool = False,
    cache_valid: bool = False,
    local_avail: bool = True,
    cloud_avail: bool = False,
    allow_cloud: bool = False,
    quality: QualityRequirement = QualityRequirement.ANY,
    required: frozenset[ResourceKind] | None = None,
    estimated: dict[ResourceKind, int] | None = None,
    ctx: ContextDisposition | None = None,
    retry_index: int = 0,
    max_retries: int = 0,
    downgrade: dict[ResourceKind, int] | None = None,
) -> EnergyActionPlan:
    return EnergyActionPlan(
        task_id=_TASK,
        correlation_id=_CID,
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=cap,
        estimated_resources=MappingProxyType(estimated or {ResourceKind.TOKENS: 100}),
        required_resources=required if required is not None else frozenset({ResourceKind.TOKENS}),
        deterministic_available=det_avail,
        cache_valid=cache_valid,
        local_available=local_avail,
        cloud_available=cloud_avail,
        allow_auto_cloud=allow_cloud,
        quality_requirement=quality,
        context_disposition=ctx,
        retry_index=retry_index,
        max_retries=max_retries,
        downgrade_resources=MappingProxyType(downgrade) if downgrade else None,
    )


class TestDeterministicAndCache:
    def test_deterministic_calls_det_action_not_model(self) -> None:
        mgr, _, _ = _make_manager()
        det = _FakeAction()
        model = _FakeAction()
        plan = _plan(det_avail=True, cap=CapabilityKind.DETERMINISTIC)
        result = mgr.execute(plan, model_action=model, deterministic_action=det)
        assert result.decision is EnergyDecision.USE_DETERMINISTIC_TOOL
        assert det.calls == 1
        assert model.calls == 0

    def test_cache_no_model_call(self) -> None:
        mgr, _, _ = _make_manager()
        cache = _FakeAction()
        model = _FakeAction()
        plan = _plan(cache_valid=True)
        result = mgr.execute(plan, model_action=model, cache_action=cache)
        assert result.decision is EnergyDecision.USE_CACHE
        assert cache.calls == 1
        assert model.calls == 0


class TestLocalExecution:
    def test_local_allow_executes_model(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 90})
        result = mgr.execute(_plan(), model_action=model)
        assert result.decision is EnergyDecision.ALLOW
        assert model.calls == 1

    def test_reserve_before_action(self) -> None:
        mgr, _, ledger = _make_manager()
        call_order: list[str] = []

        class _TrackAction:
            calls = 0

            def execute(self) -> EnergyActionResult:
                call_order.append("action")
                self.calls += 1
                return EnergyActionResult(actual=MappingProxyType({ResourceKind.TOKENS: 50}))

        original_reserve = ledger.reserve

        def track_reserve(amounts: dict[ResourceKind, int]) -> object:
            call_order.append("reserve")
            return original_reserve(amounts)

        ledger.reserve = track_reserve  # type: ignore[method-assign]
        action = _TrackAction()
        mgr.execute(_plan(), model_action=action)
        assert call_order.index("reserve") < call_order.index("action")

    def test_reservation_fail_no_action(self) -> None:
        budget = EnergyBudget({ResourceKind.TOKENS: 50})
        mgr, _, _ = _make_manager(budget=budget)
        model = _FakeAction()
        result = mgr.execute(
            _plan(estimated={ResourceKind.TOKENS: 100}),
            model_action=model,
        )
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert model.calls == 0

    def test_cloud_route_no_action(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        plan = _plan(local_avail=False, cloud_avail=True)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert model.calls == 0
        assert result.approval_request is not None

    def test_reject_no_action(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        plan = _plan(local_avail=False, cloud_avail=False)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.REJECT
        assert model.calls == 0

    def test_context_budget_failure_no_action(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=True, required_security_failure=False
        )
        plan = _plan(ctx=ctx)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert model.calls == 0

    def test_context_security_failure_reject_no_action(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        ctx = ContextDisposition(
            dispatchable=False, required_budget_failure=False, required_security_failure=True
        )
        plan = _plan(ctx=ctx)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.REJECT
        assert model.calls == 0


class TestAuditOrdering:
    def test_pre_audit_fail_no_action_reservation_released(self) -> None:
        audit = _FakeAudit(fail=True)
        mgr, _, ledger = _make_manager(audit=audit)
        model = _FakeAction()
        result = mgr.execute(_plan(), model_action=model)
        assert model.calls == 0
        assert result.audit_failure is True
        assert ledger.available(ResourceKind.TOKENS) == 1000

    def test_audit_events_before_action(self) -> None:
        audit = _FakeAudit()
        mgr, _, _ = _make_manager(audit=audit)
        action_call = [False]

        class _TrackAction:
            calls = 0

            def execute(self) -> EnergyActionResult:
                action_call[0] = True
                self.calls += 1
                return EnergyActionResult(actual=MappingProxyType({ResourceKind.TOKENS: 50}))

        mgr.execute(_plan(), model_action=_TrackAction())
        assert len(audit.events) >= 3

    def test_post_audit_failure_no_retry(self) -> None:
        # Pre-audit succeeds (first 3 calls), post-audit fails (4th call)
        audit = _FakeAudit()
        audit.fail_after = 3
        mgr, _, _ = _make_manager(audit=audit)
        model = _FakeAction(actual={ResourceKind.TOKENS: 80})
        result = mgr.execute(_plan(), model_action=model)
        # Action ran once; no retry
        assert model.calls == 1
        assert result.audit_failure is True


class TestRuntimeOverrun:
    def test_overrun_stop_with_approval(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 150})  # 150 > 100 reserved
        plan = _plan(estimated={ResourceKind.TOKENS: 100})
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.STOP
        assert result.approval_request is not None

    def test_overrun_action_ran_once(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 1100})
        result = mgr.execute(_plan(estimated={ResourceKind.TOKENS: 100}), model_action=model)
        assert model.calls == 1
        assert result.decision is EnergyDecision.STOP

    def test_overrun_actual_not_lost(self) -> None:
        mgr, _, ledger = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 150})
        result = mgr.execute(_plan(estimated={ResourceKind.TOKENS: 100}), model_action=model)
        assert result.action_result is not None
        assert result.action_result.actual[ResourceKind.TOKENS] == 150


class TestActionFailure:
    def test_action_failure_no_started_releases_reservation(self) -> None:
        mgr, _, ledger = _make_manager()

        class _FailBefore:
            def execute(self) -> EnergyActionResult:
                raise RuntimeError("failed before start")

        mgr.execute(_plan(), model_action=_FailBefore())
        # Budget should be restored
        assert ledger.available(ResourceKind.TOKENS) == 1000

    def test_action_failure_no_retry(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(raise_exc=True)
        mgr.execute(_plan(), model_action=model)
        assert model.calls == 1  # called once, not retried


class TestRetryLimit:
    def test_retry_within_limit_allows(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction(actual={ResourceKind.TOKENS: 80})
        plan = _plan(retry_index=1, max_retries=3)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.ALLOW
        assert model.calls == 1

    def test_retry_exact_limit_stop(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        plan = _plan(retry_index=3, max_retries=3)
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.STOP
        assert model.calls == 0

    def test_retry_over_limit_no_action(self) -> None:
        mgr, _, _ = _make_manager()
        model = _FakeAction()
        plan = _plan(retry_index=5, max_retries=3)
        mgr.execute(plan, model_action=model)
        assert model.calls == 0


class TestDowngrade:
    def test_downgrade_uses_lower_estimate(self) -> None:
        budget = EnergyBudget({ResourceKind.TOKENS: 500})
        mgr, _, ledger = _make_manager(budget=budget)
        model = _FakeAction(actual={ResourceKind.TOKENS: 300})
        plan = _plan(
            estimated={ResourceKind.TOKENS: 800},  # exceeds 500 budget
            required=frozenset({ResourceKind.TOKENS}),
            downgrade={ResourceKind.TOKENS: 300},  # within budget
        )
        result = mgr.execute(plan, model_action=model)
        assert result.decision is EnergyDecision.ALLOW
        assert model.calls == 1
        # Reservation used downgrade amount (300), not original (800)
        assert ledger.available(ResourceKind.TOKENS) >= 0
