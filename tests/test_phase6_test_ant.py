"""CP3 — TestAnt orchestration with fake ports (no Docker, §13.4)."""

from __future__ import annotations

from datetime import UTC, datetime

from ant_orchestrator.application.ports.test_isolation import (
    IsolatedExecutionResult,
    IsolatedExecutionSpec,
    IsolatedRunStatus,
    IsolationCapability,
    IsolationStatus,
)
from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.test_failure import RecoveryDisposition, TestReasonCode
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.test_command_profile import default_test_command_registry
from ant_orchestrator.workers.test.ant import TestAnt
from ant_orchestrator.workers.test.classifier import TestFailureClassifier
from ant_orchestrator.workers.test.provisioning import (
    BoundedRunOutput,
    CleanupOutcome,
    CleanupStatus,
    ProvisionedSnapshot,
    SnapshotProvisionStatus,
)
from ant_orchestrator.workers.test.report import TestProcessStatus, TestResult

_ALLOW = CommandPolicy(
    (CommandRule("python", allowed_arg_prefixes=(("-m", "pytest"),), allow_trailing_args=True),)
)
_DENY = CommandPolicy(())


class _FakeClock:
    def now(self) -> UtcTimestamp:
        return UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC))


class _FakeProvisioner:
    def __init__(self, calls: list[str], provisioned: ProvisionedSnapshot, cleanup: CleanupOutcome):
        self._calls = calls
        self._provisioned = provisioned
        self._cleanup = cleanup
        self.cleanup_calls = 0

    def provision(self, approved_read_scope: tuple[str, ...]) -> ProvisionedSnapshot:
        self._calls.append("provision")
        return self._provisioned

    def cleanup(self, snapshot: ProvisionedSnapshot) -> CleanupOutcome:
        self._calls.append("cleanup")
        self.cleanup_calls += 1
        return self._cleanup


class _FakeIsolation:
    def __init__(
        self, calls: list[str], capability: IsolationCapability, result: IsolatedExecutionResult
    ):
        self._calls = calls
        self._capability = capability
        self._result = result
        self.run_calls = 0
        self.specs: list[IsolatedExecutionSpec] = []

    def capability(self) -> IsolationCapability:
        self._calls.append("capability")
        return self._capability

    def run(self, spec: IsolatedExecutionSpec) -> IsolatedExecutionResult:
        self._calls.append("run")
        self.run_calls += 1
        self.specs.append(spec)
        return self._result


class _FakeOutputReader:
    def __init__(self, output: BoundedRunOutput | None):
        self._output = output

    def read(self, runtime_output_ref: str) -> BoundedRunOutput | None:
        return self._output


def _verified() -> ProvisionedSnapshot:
    return ProvisionedSnapshot(
        SnapshotProvisionStatus.BUILT_VERIFIED,
        snapshot_ref="snap-abc",
        runtime_output_ref="out-abc",
        manifest_digest="f" * 64,
        file_count=3,
        total_bytes=120,
        evidence_refs=("audit:snap",),
    )


def _available() -> IsolationCapability:
    return IsolationCapability(IsolationStatus.AVAILABLE, backend_ref="container")


def _task(
    command_key: str = "pytest.acceptance", targets: tuple[str, ...] = ("tests/unit",)
) -> TestTask:
    return TestTask(
        task_ref="t1",
        logical_action_id="t1-test",
        command_key=command_key,
        targets=targets,
    )


def _scope(**over: object) -> TestExecutionScope:
    base: dict[str, object] = dict(
        attempt_id="att-1",
        run_id="run-1",
        logical_action_id="t1-test",
        canonical_read_scope=("tests", "src"),
        command_profile_key="pytest.acceptance",
        idempotency_key="idem-1",
    )
    base.update(over)
    return TestExecutionScope(**base)  # type: ignore[arg-type]


def _ant(
    calls: list[str],
    *,
    policy: CommandPolicy = _ALLOW,
    provisioned: ProvisionedSnapshot | None = None,
    cleanup: CleanupOutcome | None = None,
    capability: IsolationCapability | None = None,
    result: IsolatedExecutionResult | None = None,
    output: BoundedRunOutput | None = None,
) -> tuple[TestAnt, _FakeProvisioner, _FakeIsolation]:
    prov = _FakeProvisioner(
        calls, provisioned or _verified(), cleanup or CleanupOutcome(CleanupStatus.CLEAN)
    )
    iso = _FakeIsolation(
        calls,
        capability or _available(),
        result or IsolatedExecutionResult(IsolatedRunStatus.COMPLETED, exit_code=0, duration_ms=10),
    )
    ant = TestAnt(
        command_registry=default_test_command_registry(),
        command_policy=policy,
        provisioner=prov,
        isolation=iso,
        classifier=TestFailureClassifier(),
        clock=_FakeClock(),
        output_reader=_FakeOutputReader(output),
    )
    return ant, prov, iso


def test_pass_end_to_end() -> None:
    calls: list[str] = []
    output = BoundedRunOutput("==== 5 passed in 0.1s ====", original_bytes=30)
    ant, prov, iso = _ant(calls, output=output)
    res = ant.execute(_task(), _scope(), "run-1")
    assert calls == ["capability", "provision", "run", "cleanup"]
    assert res.outcome is not None and res.outcome.outcome is WorkerOutcome.SUCCESS
    assert res.worker_report is not None and res.worker_report.result is WorkerOutcome.SUCCESS
    assert res.worker_report.files_changed == ()
    assert res.structured_report.is_success
    assert res.structured_report.counts.passed == 5
    assert res.outcome.provider_invoked is False
    assert iso.run_calls == 1 and prov.cleanup_calls == 1
    assert iso.specs[0].snapshot_ref == "snap-abc"


def test_deterministic_test_failure() -> None:
    calls: list[str] = []
    ant, _, iso = _ant(
        calls,
        result=IsolatedExecutionResult(IsolatedRunStatus.COMPLETED, exit_code=1, duration_ms=9),
    )
    res = ant.execute(_task(), _scope(), "run-1")
    assert res.structured_report.test_result is TestResult.FAILED
    assert res.outcome is not None and res.outcome.outcome is WorkerOutcome.ESCALATION
    assert res.outcome.disposition is RecoveryDisposition.ESCALATE
    assert iso.run_calls == 1


def test_plain_timeout_does_not_retry() -> None:
    calls: list[str] = []
    ant, _, _ = _ant(
        calls, result=IsolatedExecutionResult(IsolatedRunStatus.TIMEOUT, duration_ms=120000)
    )
    res = ant.execute(_task(), _scope(), "run-1")
    assert res.structured_report.process_status is TestProcessStatus.TIMEOUT
    assert (
        res.outcome is not None and res.outcome.reason_code is TestReasonCode.TEST_DEADLINE_EXCEEDED
    )
    assert res.outcome.outcome is WorkerOutcome.ESCALATION


def test_backend_unavailable_does_not_run() -> None:
    calls: list[str] = []
    cap = IsolationCapability(
        IsolationStatus.UNAVAILABLE,
        backend_ref="container",
        reason_code=TestReasonCode.EXECUTION_ISOLATION_UNAVAILABLE,
    )
    ant, prov, iso = _ant(calls, capability=cap)
    res = ant.execute(_task(), _scope(), "run-1")
    assert iso.run_calls == 0 and prov.cleanup_calls == 0
    assert "provision" not in calls
    assert res.structured_report.process_status is TestProcessStatus.ISOLATION_UNAVAILABLE
    assert res.structured_report.exit_code is None
    assert res.outcome is not None and res.outcome.outcome is WorkerOutcome.ESCALATION


def test_snapshot_digest_mismatch_fails_closed() -> None:
    calls: list[str] = []
    bad = ProvisionedSnapshot(
        SnapshotProvisionStatus.INTEGRITY_MISMATCH, evidence_refs=("audit:bad",)
    )
    ant, prov, iso = _ant(calls, provisioned=bad)
    res = ant.execute(_task(), _scope(), "run-1")
    assert iso.run_calls == 0
    assert prov.cleanup_calls == 1
    assert res.outcome is not None
    assert res.outcome.category.value == "isolation_violation"
    assert res.outcome.outcome is WorkerOutcome.PERMANENT_FAILURE


def test_command_profile_denial_does_not_run() -> None:
    calls: list[str] = []
    ant, prov, iso = _ant(calls, policy=_DENY)
    res = ant.execute(_task(), _scope(), "run-1")
    assert calls == []  # short-circuit before capability/provision/run
    assert iso.run_calls == 0 and prov.cleanup_calls == 0
    assert res.outcome is not None and res.outcome.outcome is WorkerOutcome.PERMANENT_FAILURE
    assert res.outcome.reason_code is TestReasonCode.COMMAND_POLICY_DENIED


def test_identity_mismatch_does_not_run() -> None:
    calls: list[str] = []
    ant, prov, iso = _ant(calls)
    res = ant.execute(_task(), _scope(run_id="other-run"), "run-1")
    assert iso.run_calls == 0
    assert res.outcome is not None
    assert res.outcome.reason_code is TestReasonCode.EXECUTION_BOUNDARY_DENIED


def test_target_out_of_scope_is_boundary_failure() -> None:
    calls: list[str] = []
    ant, _, iso = _ant(calls)
    res = ant.execute(_task(targets=("docs/secret.md",)), _scope(), "run-1")
    assert iso.run_calls == 0
    assert res.outcome is not None
    assert res.outcome.reason_code is TestReasonCode.EXECUTION_BOUNDARY_DENIED


def test_cleanup_security_impact_overrides_pass() -> None:
    calls: list[str] = []
    ant, prov, iso = _ant(
        calls,
        cleanup=CleanupOutcome(CleanupStatus.FAILED_SECURITY_IMPACT, evidence_refs=("audit:leak",)),
    )
    res = ant.execute(_task(), _scope(), "run-1")
    assert iso.run_calls == 1 and prov.cleanup_calls == 1
    assert not res.structured_report.is_success
    assert res.outcome is not None
    assert res.outcome.category.value == "isolation_violation"


def test_cancellation_result() -> None:
    calls: list[str] = []
    ant, _, _ = _ant(
        calls, result=IsolatedExecutionResult(IsolatedRunStatus.CANCELLED, duration_ms=5)
    )
    res = ant.execute(_task(), _scope(), "run-1")
    assert res.cancelled is True
    assert res.outcome is None
    assert res.worker_report is None
    assert res.structured_report.recovery_disposition is RecoveryDisposition.TERMINAL_CANCELLED


def test_unknown_backend_status_is_bounded() -> None:
    calls: list[str] = []
    ant, _, _ = _ant(
        calls, result=IsolatedExecutionResult(IsolatedRunStatus.LAUNCH_FAILED, duration_ms=3)
    )
    res = ant.execute(_task(), _scope(), "run-1")
    assert res.outcome is not None and res.outcome.outcome is WorkerOutcome.ESCALATION
    assert res.outcome.reason_code is TestReasonCode.ISOLATION_SETUP_FAILED


def test_counts_unavailable_when_no_output_reader() -> None:
    calls: list[str] = []
    ant, _, _ = _ant(calls, output=None)
    res = ant.execute(_task(), _scope(), "run-1")
    assert res.structured_report.counts.available is False
    assert res.structured_report.is_success
