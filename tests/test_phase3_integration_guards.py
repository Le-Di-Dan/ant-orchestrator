"""CP9 Phase 3 integration — context security, cloud, audit fail-closed guards."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import MappingProxyType

from ant_orchestrator.application.ports.audit import AuditEvent
from ant_orchestrator.application.ports.context_builder import ArtifactRequirement
from ant_orchestrator.application.ports.energy import (
    ApprovalReason,
    EnergyActionResult,
    EnergyDecision,
    ResourceKind,
)
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.phase3_harness import (
    ctx_disposition,
    make_ctx_build_request,
    make_manager,
    make_pkg_builder,
    make_plan,
)

# ---------------------------------------------------------------------------
# Case 3: context security rejection
# ---------------------------------------------------------------------------


class TestContextSecurityRejection:
    def test_secret_file_required_no_action(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("SECRET=abc123", encoding="utf-8")
        audit = FakeAuditSink()
        builder = make_pkg_builder(tmp_path, audit)
        mgr, _ = make_manager(audit)

        req = make_ctx_build_request(".env", ArtifactRequirement.REQUIRED)
        pkg = asyncio.run(builder.build(req))

        assert pkg.manifest.dispatchable is False
        ctx = ctx_disposition(pkg.manifest.rejected, pkg.manifest.dispatchable)
        assert ctx.required_security_failure is True

        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({}))

        result = mgr.execute(make_plan(ctx=ctx), model_action=_MockAction())
        assert result.decision is EnergyDecision.REJECT
        assert action_count[0] == 0
        assert result.approval_request is None
        for e in audit.events:
            for v in e.detail.values():
                assert "abc123" not in v

    def test_security_rejection_no_cloud_approval(self, tmp_path: Path) -> None:
        (tmp_path / ".env").write_text("KEY=val", encoding="utf-8")
        audit = FakeAuditSink()
        builder = make_pkg_builder(tmp_path, audit)
        mgr, _ = make_manager(audit)

        req = make_ctx_build_request(".env", ArtifactRequirement.REQUIRED)
        pkg = asyncio.run(builder.build(req))
        ctx = ctx_disposition(pkg.manifest.rejected, pkg.manifest.dispatchable)

        result = mgr.execute(make_plan(ctx=ctx, cloud_avail=True), model_action=None)
        assert result.decision is EnergyDecision.REJECT
        if result.approval_request is not None:
            assert result.approval_request.reason is not ApprovalReason.CLOUD_REQUIRES_APPROVAL


# ---------------------------------------------------------------------------
# Case 5: cloud approval
# ---------------------------------------------------------------------------


class TestCloudApproval:
    def test_cloud_route_no_action(self) -> None:
        audit = FakeAuditSink()
        mgr, _ = make_manager(audit)
        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({}))

        result = mgr.execute(
            make_plan(local_avail=False, cloud_avail=True), model_action=_MockAction()
        )
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert action_count[0] == 0
        ar = result.approval_request
        assert ar is not None
        assert ar.proposed_route is EnergyDecision.ESCALATE_CLOUD
        assert ar.reason is ApprovalReason.CLOUD_REQUIRES_APPROVAL

    def test_cloud_approval_no_model_sdk_import(self) -> None:
        audit = FakeAuditSink()
        mgr, _ = make_manager(audit)
        result = mgr.execute(make_plan(local_avail=False, cloud_avail=True))
        assert result.decision is EnergyDecision.PENDING_APPROVAL
        assert result.approval_request is not None
        ar = result.approval_request
        assert not hasattr(ar, "provider")
        assert not hasattr(ar, "model_name")
        assert not hasattr(ar, "api_key")


# ---------------------------------------------------------------------------
# Case 7: audit fail-closed
# ---------------------------------------------------------------------------


class TestAuditFailClosed:
    def test_pre_audit_failure_no_action_reservation_released(self) -> None:
        from ant_orchestrator.application.ports.energy import EnergyBudget

        class _FailAudit(FakeAuditSink):
            def write(self, event: AuditEvent) -> None:
                raise RuntimeError("audit fail")

        budget = EnergyBudget({ResourceKind.TOKENS: 2000})
        mgr, ledger = make_manager(_FailAudit(), budget)
        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(actual=MappingProxyType({}))

        result = mgr.execute(make_plan(estimated=100), model_action=_MockAction())
        assert action_count[0] == 0
        assert result.audit_failure is True
        assert ledger.available(ResourceKind.TOKENS) == 2000

    def test_post_audit_failure_action_ran_once_no_retry(self) -> None:
        class _FailAfter3(FakeAuditSink):
            def __init__(self) -> None:
                super().__init__()
                self._n = 0

            def write(self, event: AuditEvent) -> None:
                self._n += 1
                if self._n > 3:
                    raise RuntimeError("post-audit fail")
                super().write(event)  # type: ignore[arg-type]

        mgr, _ = make_manager(_FailAfter3())
        action_count = [0]

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                action_count[0] += 1
                return EnergyActionResult(
                    actual=MappingProxyType({ResourceKind.TOKENS: 50}),
                    side_effect_started=True,
                )

        result = mgr.execute(make_plan(estimated=100), model_action=_MockAction())
        assert action_count[0] == 1
        assert result.audit_failure is True

    def test_post_audit_failure_actual_consumed(self) -> None:
        class _FailPost(FakeAuditSink):
            def __init__(self) -> None:
                super().__init__()
                self._n = 0

            def write(self, event: AuditEvent) -> None:
                self._n += 1
                if self._n > 3:
                    raise RuntimeError("post-audit fail")
                super().write(event)  # type: ignore[arg-type]

        from ant_orchestrator.application.ports.energy import EnergyBudget

        budget = EnergyBudget({ResourceKind.TOKENS: 2000})
        mgr, ledger = make_manager(_FailPost(), budget)

        class _MockAction:
            def execute(self) -> EnergyActionResult:
                return EnergyActionResult(
                    actual=MappingProxyType({ResourceKind.TOKENS: 80}),
                    side_effect_started=True,
                )

        mgr.execute(make_plan(estimated=100), model_action=_MockAction())
        assert ledger.available(ResourceKind.TOKENS) < 2000
