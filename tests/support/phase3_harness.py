"""Shared harness for Phase 3 integration tests (CP9)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from ant_orchestrator.application.ports.audit import CorrelationId
from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequirement,
    ConsumerKind,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
)
from ant_orchestrator.application.ports.energy import (
    ActionKind,
    CapabilityKind,
    ContextDisposition,
    EnergyActionPlan,
    EnergyBudget,
    QualityRequirement,
    ResourceKind,
)
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackageBuilder, ManifestRejection
from ant_orchestrator.context.selection import ContextSelector, RejectionReason
from ant_orchestrator.core.domain.value_objects import TaskId, UtcTimestamp
from ant_orchestrator.energy.enforcement import EnforcementPolicy
from ant_orchestrator.energy.manager import EnergyManager
from ant_orchestrator.energy.reservation import ReservationLedger
from ant_orchestrator.energy.routing import RoutingPolicy
from ant_orchestrator.execution.bounded_fs import BoundedFileSystemAdapter, BoundedFsConfig
from ant_orchestrator.execution.bounded_shell import BoundedShellConfig, SubprocessShellAdapter
from ant_orchestrator.execution.output_limit import OutputLimit
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

PY = Path(sys.executable).resolve()
TS = UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))
TASK = TaskId("p3-job")
BUDGET = EnergyBudget({ResourceKind.TOKENS: 2000, ResourceKind.API_CALLS: 10})
CONSUMER = ContextConsumer(ConsumerKind.WORKER, "p3-worker")

_SECURITY_REASONS = {RejectionReason.SECRET_FILE, RejectionReason.OUTSIDE_SCOPE}


def make_fs(tmp_path: Path, audit: FakeAuditSink) -> BoundedFileSystemAdapter:
    scope = PathScope.build(read_roots=(tmp_path,), write_roots=(tmp_path,))
    return BoundedFileSystemAdapter(
        config=BoundedFsConfig(workspace_root=tmp_path),
        path_policy=PathPolicy(scope, workspace_root=tmp_path),
        redactor=Redactor(),
        audit_sink=audit,
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="FS"),
    )


def make_shell(tmp_path: Path, audit: FakeAuditSink) -> SubprocessShellAdapter:
    rules = (
        CommandRule(executable="python", allowed_arg_prefixes=((),), allow_trailing_args=True),
    )
    scope = PathScope.build(read_roots=(tmp_path,), write_roots=())
    return SubprocessShellAdapter(
        config=BoundedShellConfig(
            workspace_root=tmp_path,
            trusted_executables={"python": PY},
            output_limit=OutputLimit(4096),
        ),
        command_policy=CommandPolicy(rules),
        cwd_policy=PathPolicy(scope, workspace_root=tmp_path),
        redactor=Redactor(),
        audit_sink=audit,
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="SH"),
    )


def make_manager(
    audit: FakeAuditSink, budget: EnergyBudget = BUDGET
) -> tuple[EnergyManager, ReservationLedger]:
    ledger = ReservationLedger(budget, FakeClock(TS), SequentialIdGenerator(prefix="L"))
    mgr = EnergyManager(
        ledger=ledger,
        audit_sink=audit,
        routing_policy=RoutingPolicy(),
        enforcement_policy=EnforcementPolicy(),
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="M"),
    )
    return mgr, ledger


def make_pkg_builder(tmp_path: Path, audit: FakeAuditSink) -> ContextPackageBuilder:
    return ContextPackageBuilder(
        fs=make_fs(tmp_path, audit),
        estimator=CharacterHeuristicEstimator(),
        selector=ContextSelector(),
        audit_sink=audit,
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="P"),
    )


def ctx_disposition(
    manifest_rejected: tuple[ManifestRejection, ...], dispatchable: bool
) -> ContextDisposition:
    required_security = any(
        r.reason in _SECURITY_REASONS and r.requirement is ArtifactRequirement.REQUIRED
        for r in manifest_rejected
    )
    required_budget = any(
        r.reason is RejectionReason.BUDGET_EXCEEDED
        and r.requirement is ArtifactRequirement.REQUIRED
        for r in manifest_rejected
    )
    return ContextDisposition(
        dispatchable=dispatchable,
        required_security_failure=required_security,
        required_budget_failure=required_budget,
    )


def make_plan(
    ctx: ContextDisposition | None = None,
    estimated: int = 100,
    local_avail: bool = True,
    cloud_avail: bool = False,
) -> EnergyActionPlan:
    return EnergyActionPlan(
        task_id=TASK,
        correlation_id=CorrelationId("corr-p3"),
        action_kind=ActionKind.LOCAL_LLM_INFERENCE,
        required_capability=CapabilityKind.LLM_INFERENCE,
        estimated_resources=MappingProxyType({ResourceKind.TOKENS: estimated}),
        required_resources=frozenset({ResourceKind.TOKENS}),
        deterministic_available=False,
        cache_valid=False,
        local_available=local_avail,
        cloud_available=cloud_avail,
        allow_auto_cloud=False,
        quality_requirement=QualityRequirement.ANY,
        context_disposition=ctx,
    )


def make_ctx_build_request(
    path: str,
    requirement: ArtifactRequirement = ArtifactRequirement.OPTIONAL,
    budget: ContextBudget | None = None,
) -> ContextBuildRequest:
    from ant_orchestrator.application.ports.context_builder import ArtifactRequest

    if budget is None:
        budget = ContextBudget(max_input_tokens=5000, max_files=5, max_file_tokens=2000)
    return ContextBuildRequest(
        task_id=TASK,
        consumer=CONSUMER,
        requests=(ArtifactRequest(path, requirement),),
        excluded=(),
        budget=budget,
    )
