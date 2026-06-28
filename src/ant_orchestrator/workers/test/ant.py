"""Test Ant — read-only, isolation-enforced single-run orchestration (PHASE_6_PLAN CP3).

Fail-closed ordering: verify identity/authority → resolve the trusted command profile
(policy gate) → preflight isolation capability → build + verify the exact-byte snapshot →
run the command through the :class:`TestIsolationPort` → collect bounded facts → cleanup →
classify deterministically → assemble the structured report, worker report and graph
outcome. The worker is read-only by construction: it receives NO mutator, Git adapter,
provider, subprocess, free-form argv/env/mount or Docker backend — only typed ports. It
never retries, regroups, escalates, persists or settles energy (those belong to CP4/CP5).
"""

from __future__ import annotations

import hashlib

from ant_orchestrator.application.ports.test_isolation import (
    IsolatedExecutionSpec,
    IsolationCapability,
    TestIsolationPort,
)
from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask
from ant_orchestrator.config.constants import (
    MAX_TEST_EVIDENCE_REFS,
    TEST_CONTAINER_PIDS_LIMIT,
    TEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS,
)
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.security.command_policy import CommandPolicy
from ant_orchestrator.security.test_command_profile import TestCommandError as _CmdError
from ant_orchestrator.security.test_command_profile import (
    TestCommandPolicyDenied,
    TestCommandRegistry,
    TestCommandResolver,
    UnknownCommandKey,
)
from ant_orchestrator.security.test_command_profile import TestTargetRejected as _TargetRejected
from ant_orchestrator.workers.test.classifier import (
    PreflightStatus,
    TestExecutionFacts,
    TestFailureClassifier,
)
from ant_orchestrator.workers.test.provisioning import (
    ProvisionedSnapshot,
    TestOutputReader,
    TestSnapshotProvisioner,
)
from ant_orchestrator.workers.test.pytest_outcome import parse_counts
from ant_orchestrator.workers.test.report import TestCounts
from ant_orchestrator.workers.test.result import RunContext, TestExecutionResult, assemble

_TIMEOUT_MS = int(TEST_EXECUTION_DEFAULT_TIMEOUT_SECONDS * 1000)


class TestAnt:
    """Read-only Test Ant worker — testable with fakes; never mutates or calls a model."""

    __test__ = False  # domain term; not a pytest test class

    def __init__(
        self,
        *,
        command_registry: TestCommandRegistry,
        command_policy: CommandPolicy,
        provisioner: TestSnapshotProvisioner,
        isolation: TestIsolationPort,
        classifier: TestFailureClassifier,
        clock: Clock,
        output_reader: TestOutputReader | None = None,
    ) -> None:
        self._registry = command_registry
        self._resolver = TestCommandResolver(command_registry, command_policy)
        self._provisioner = provisioner
        self._isolation = isolation
        self._classifier = classifier
        self._clock = clock
        self._output = output_reader

    def execute(
        self, task: TestTask, scope: TestExecutionScope, run_id: str
    ) -> TestExecutionResult:
        """Run one read-only acceptance attempt and return its structured result."""
        argv, digest, version, preflight = self._resolve(task, scope, run_id)
        base = self._context(task, scope, run_id, argv, digest, version)
        if preflight is not PreflightStatus.OK:
            return self._classify(TestExecutionFacts(preflight=preflight), base)

        capability = self._isolation.capability()
        if not capability.is_available:
            facts = TestExecutionFacts(
                capability_available=False, evidence_refs=self._cap_refs(capability)
            )
            return self._classify(facts, self._with(base, backend_ref=capability.backend_ref))

        provisioned = self._provisioner.provision(scope.canonical_read_scope)
        if not provisioned.is_verified:
            cleanup = self._provisioner.cleanup(provisioned)
            facts = TestExecutionFacts(
                snapshot=provisioned.status,
                evidence_refs=provisioned.evidence_refs[:MAX_TEST_EVIDENCE_REFS],
            )
            ctx = self._with(
                base, provisioned=provisioned, cleanup=cleanup, backend_ref=capability.backend_ref
            )
            return self._classify(facts, ctx)

        return self._run(task, scope, provisioned, capability, base)

    # --- execution -----------------------------------------------------------
    def _run(
        self,
        task: TestTask,
        scope: TestExecutionScope,
        provisioned: ProvisionedSnapshot,
        capability: IsolationCapability,
        base: RunContext,
    ) -> TestExecutionResult:
        spec = IsolatedExecutionSpec(
            snapshot_ref=provisioned.snapshot_ref or "snapshot",
            runtime_output_ref=provisioned.runtime_output_ref or "out",
            command_profile_key=scope.command_profile_key,
            timeout_ms=_TIMEOUT_MS,
            max_processes=TEST_CONTAINER_PIDS_LIMIT,
        )
        started = self._now()
        run_result = self._isolation.run(spec)
        finished = self._now()
        counts, output = self._read_output(provisioned, run_result.status)
        cleanup = self._provisioner.cleanup(provisioned)
        facts = TestExecutionFacts(
            run_status=run_result.status,
            exit_code=run_result.exit_code,
            cleanup=cleanup.status,
            evidence_refs=tuple(run_result.evidence_refs)[:MAX_TEST_EVIDENCE_REFS],
        )
        ctx = self._with(
            base,
            provisioned=provisioned,
            run_result=run_result,
            counts=counts,
            output=output,
            cleanup=cleanup,
            backend_ref=capability.backend_ref,
            started_at=started,
            finished_at=finished,
        )
        return self._classify(facts, ctx)

    def _read_output(
        self, provisioned: ProvisionedSnapshot, status: object
    ) -> tuple[TestCounts, object | None]:
        from ant_orchestrator.application.ports.test_isolation import IsolatedRunStatus

        if self._output is None or status is not IsolatedRunStatus.COMPLETED:
            return TestCounts.unavailable(), None
        output = self._output.read(provisioned.runtime_output_ref or "out")
        if output is None:
            return TestCounts.unavailable(), None
        return parse_counts(output.text), output

    # --- preflight -----------------------------------------------------------
    def _resolve(
        self, task: TestTask, scope: TestExecutionScope, run_id: str
    ) -> tuple[tuple[str, ...], str, int, PreflightStatus]:
        identity = self._check_identity(task, scope, run_id)
        if identity is not PreflightStatus.OK:
            return (), self._digest((task.command_key,)), 1, identity
        try:
            argv = self._resolver.resolve(task.command_key, task.targets)
        except TestCommandPolicyDenied:
            return (), self._digest((task.command_key,)), 1, PreflightStatus.COMMAND_POLICY_DENIED
        except (UnknownCommandKey, _TargetRejected, _CmdError):
            return (), self._digest((task.command_key,)), 1, PreflightStatus.INVALID_COMMAND
        version = self._registry.get(task.command_key).version
        return argv, self._digest(argv), version, PreflightStatus.OK

    @staticmethod
    def _check_identity(task: TestTask, scope: TestExecutionScope, run_id: str) -> PreflightStatus:
        if not run_id or run_id != scope.run_id:
            return PreflightStatus.IDENTITY_MISMATCH
        if task.logical_action_id != scope.logical_action_id:
            return PreflightStatus.IDENTITY_MISMATCH
        if task.command_key != scope.command_profile_key:
            return PreflightStatus.IDENTITY_MISMATCH
        if not _targets_in_scope(task.targets, scope.canonical_read_scope):
            return PreflightStatus.SCOPE_VIOLATION
        return PreflightStatus.OK

    # --- helpers -------------------------------------------------------------
    def _classify(self, facts: TestExecutionFacts, ctx: RunContext) -> TestExecutionResult:
        return assemble(self._classifier.classify(facts), ctx)

    def _context(
        self,
        task: TestTask,
        scope: TestExecutionScope,
        run_id: str,
        argv: tuple[str, ...],
        digest: str,
        version: int,
    ) -> RunContext:
        now = self._now()
        return RunContext(
            run_id=run_id,
            attempt_ref=scope.attempt_id,
            logical_action_ref=scope.logical_action_id,
            command_key=task.command_key,
            profile_version=version,
            sanitized_argv=argv,
            argv_digest=digest,
            approved_targets=task.targets,
            files_read=scope.canonical_read_scope,
            started_at=now,
            finished_at=now,
        )

    @staticmethod
    def _with(base: RunContext, **changes: object) -> RunContext:
        from dataclasses import replace

        return replace(base, **changes)  # type: ignore[arg-type]

    def _now(self) -> str:
        return self._clock.now().value.isoformat()

    @staticmethod
    def _cap_refs(capability: IsolationCapability) -> tuple[str, ...]:
        return (capability.reason_code.value,) if capability.reason_code else ()

    @staticmethod
    def _digest(argv: tuple[str, ...]) -> str:
        return hashlib.sha256("\x00".join(argv).encode("utf-8")).hexdigest()


def _targets_in_scope(targets: tuple[str, ...], scope: tuple[str, ...]) -> bool:
    entries = [e.replace("\\", "/").rstrip("/") for e in scope]
    for raw in targets:
        target = raw.replace("\\", "/")
        if not any(target == e or target.startswith(e + "/") for e in entries):
            return False
    return True
