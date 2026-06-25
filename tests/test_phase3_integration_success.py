"""CP9 Phase 3 integration — happy path, context/budget, overrun, JSONL evidence."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import MappingProxyType

from ant_orchestrator.adapters.jsonl_audit_sink import JsonlAuditSink
from ant_orchestrator.application.ports.context_builder import ArtifactRequirement, ContextBudget
from ant_orchestrator.application.ports.energy import (
    ApprovalReason,
    EnergyActionResult,
    EnergyDecision,
    ResourceKind,
)
from ant_orchestrator.application.ports.shell import ShellRequest
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.energy.manager import EnergyManager
from ant_orchestrator.energy.reservation import ReservationLedger
from ant_orchestrator.energy.routing import RoutingPolicy
from ant_orchestrator.security.redaction.redactor import Redactor
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.phase3_harness import (
    BUDGET,
    TS,
    ctx_disposition,
    make_ctx_build_request,
    make_manager,
    make_pkg_builder,
    make_plan,
    make_shell,
)

# ---------------------------------------------------------------------------
# Case 1: local successful path
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_context_to_execution_full_flow(self, tmp_path: Path) -> None:
        (tmp_path / "data.txt").write_text("hello world content", encoding="utf-8")
        script = tmp_path / "work.py"
        script.write_text("print('done')\n", encoding="utf-8")

        audit = FakeAuditSink()
        builder = make_pkg_builder(tmp_path, audit)
        mgr, ledger = make_manager(audit)

        pkg = asyncio.run(builder.build(make_ctx_build_request("data.txt")))

        assert pkg.manifest.dispatchable is True
        assert not any(a.path == ".env" for a in pkg.artifacts)
        assert len(pkg.artifacts) == 1

        ctx = ctx_disposition(pkg.manifest.rejected, pkg.manifest.dispatchable)
        assert ctx.required_security_failure is False
        assert ctx.required_budget_failure is False

        shell = make_shell(tmp_path, audit)
        action_count = [0]

        class _ShellAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                asyncio.run(shell.run(ShellRequest(argv=("python", str(script)))))
                return EnergyActionResult(
                    actual=MappingProxyType({ResourceKind.TOKENS: 50}),
                    side_effect_started=True,
                )

        result = mgr.execute(make_plan(ctx=ctx, estimated=100), model_action=_ShellAction())
        assert result.decision is EnergyDecision.ALLOW
        assert action_count[0] == 1
        assert ledger.available(ResourceKind.TOKENS) >= 0
        assert len(audit.events) >= 3


# ---------------------------------------------------------------------------
# Case 2: context required artifact over context budget
# ---------------------------------------------------------------------------


class TestContextOverBudget:
    def test_required_over_budget_no_action(self, tmp_path: Path) -> None:
        (tmp_path / "large.txt").write_text("x" * 5000, encoding="utf-8")
        audit = FakeAuditSink()
        builder = make_pkg_builder(tmp_path, audit)
        mgr, _ = make_manager(audit)

        tight_budget = ContextBudget(max_input_tokens=10, max_files=5, max_file_tokens=10)
        req = make_ctx_build_request("large.txt", ArtifactRequirement.REQUIRED, budget=tight_budget)
        pkg = asyncio.run(builder.build(req))

        assert pkg.manifest.dispatchable is False
        ctx = ctx_disposition(pkg.manifest.rejected, pkg.manifest.dispatchable)
        assert ctx.required_budget_failure is True

        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({}))

        result = mgr.execute(make_plan(ctx=ctx), model_action=_MockAction())
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert action_count[0] == 0
        assert result.approval_request is not None
        assert result.approval_request.reason is ApprovalReason.CONTEXT_BUDGET_EXCEEDED


# ---------------------------------------------------------------------------
# Case 4: energy reservation failure
# ---------------------------------------------------------------------------


class TestEnergyReservationFailure:
    def test_budget_insufficient_no_action(self) -> None:
        from ant_orchestrator.application.ports.energy import EnergyBudget

        audit = FakeAuditSink()
        small_budget = EnergyBudget({ResourceKind.TOKENS: 50})
        mgr, _ = make_manager(audit, small_budget)

        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({}))

        result = mgr.execute(make_plan(estimated=100), model_action=_MockAction())
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert action_count[0] == 0


# ---------------------------------------------------------------------------
# Case 6: runtime overrun
# ---------------------------------------------------------------------------


class TestRuntimeOverrun:
    def test_overrun_stop_action_ran_once(self) -> None:
        audit = FakeAuditSink()
        mgr, _ = make_manager(audit)
        action_count = [0]

        class _OverrunAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(
                    actual=MappingProxyType({ResourceKind.TOKENS: 5000}),
                    side_effect_started=True,
                )

        result = mgr.execute(make_plan(estimated=100), model_action=_OverrunAction())
        assert result.decision is EnergyDecision.STOP
        assert action_count[0] == 1
        assert result.approval_request is not None
        assert result.approval_request.reason is ApprovalReason.RUNTIME_BUDGET_EXCEEDED
        assert result.action_result is not None

    def test_overrun_no_follow_up_action(self) -> None:
        audit = FakeAuditSink()
        mgr, _ = make_manager(audit)
        action_count = [0]

        class _OverrunAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({ResourceKind.TOKENS: 5000}))

        mgr.execute(make_plan(estimated=100), model_action=_OverrunAction())
        assert action_count[0] == 1


# ---------------------------------------------------------------------------
# Case 8: JSONL audit evidence
# ---------------------------------------------------------------------------


class TestJsonlEvidence:
    def test_jsonl_audit_trail(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        sink = JsonlAuditSink(logs_dir=logs_dir, clock=FakeClock(TS), redactor=Redactor())
        ledger = ReservationLedger(BUDGET, FakeClock(TS), SequentialIdGenerator())
        mgr = EnergyManager(
            ledger=ledger,
            audit_sink=sink,
            routing_policy=RoutingPolicy(),
            enforcement_policy=EnforcementPolicy(),
            clock=FakeClock(TS),
            id_gen=SequentialIdGenerator(),
        )

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                return EnergyActionResult(
                    actual=MappingProxyType({ResourceKind.TOKENS: 80}),
                    side_effect_started=True,
                )

        mgr.execute(make_plan(estimated=100), model_action=_MockAction())

        log_files = list(logs_dir.glob("audit-*.jsonl"))
        assert len(log_files) == 1
        lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) >= 3

        for line in lines:
            event = json.loads(line)
            assert event["schema_version"] == 1
            for v in event["detail"].values():
                assert "BEGIN PRIVATE KEY" not in v
                assert "ghp_" not in v

        types = {json.loads(line)["event_type"] for line in lines}
        assert "routing_decision" in types
        assert "energy_reservation" in types
        assert "energy_enforcement" in types

    def test_jsonl_correlation_id_consistent(self, tmp_path: Path) -> None:
        logs_dir = tmp_path / "logs"
        sink = JsonlAuditSink(logs_dir=logs_dir, clock=FakeClock(TS), redactor=Redactor())
        ledger = ReservationLedger(BUDGET, FakeClock(TS), SequentialIdGenerator())
        mgr = EnergyManager(
            ledger=ledger,
            audit_sink=sink,
            routing_policy=RoutingPolicy(),
            enforcement_policy=EnforcementPolicy(),
            clock=FakeClock(TS),
            id_gen=SequentialIdGenerator(),
        )

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                return EnergyActionResult(actual=MappingProxyType({ResourceKind.TOKENS: 50}))

        mgr.execute(make_plan(estimated=100), model_action=_MockAction())

        log_files = list(logs_dir.glob("audit-*.jsonl"))
        lines = log_files[0].read_text(encoding="utf-8").strip().splitlines()
        cids = {json.loads(line)["correlation_id"] for line in lines}
        assert len(cids) == 1
