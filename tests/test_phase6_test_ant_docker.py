"""CP3 — TestAnt end-to-end through the REAL Docker isolation backend (gated).

Proves the full path: ``TestAnt`` → command profile → exact-byte snapshot →
``TestIsolationPort`` (Docker) → structured report. Skipped with a clear reason where
Docker, the pinned image, or pytest-in-image are absent (no implicit pull). CP2 already
proves the enforcement matrix; this only confirms the worker wiring + a host-path-free
report + clean container cleanup.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ant_orchestrator.config.constants import TEST_ISOLATION_IMAGE_REF
from ant_orchestrator.execution.bounded_shell import BoundedShellConfig, SubprocessShellAdapter
from ant_orchestrator.execution.output_limit import OutputLimit
from ant_orchestrator.execution.test_snapshot import (
    ExecutionSnapshotBuilder,
    SnapshotError,
    cleanup_snapshot,
)
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.security.test_command_profile import default_test_command_registry
from ant_orchestrator.workers.test.ant import TestAnt
from ant_orchestrator.workers.test.classifier import TestFailureClassifier
from ant_orchestrator.workers.test.provisioning import (
    CleanupOutcome,
    CleanupStatus,
    ProvisionedSnapshot,
    SnapshotProvisionStatus,
)
from ant_orchestrator.workers.test.report import TestResult
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.phase3_harness import TS


def _docker() -> Path | None:
    found = shutil.which("docker")
    return Path(found) if found else None


def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, timeout=60)


class _RealProvisioner:
    """Wraps the CP2 snapshot builder + cleanup behind the CP3 provisioner port."""

    def __init__(self, canonical_root: Path, snapshot_root: Path) -> None:
        self._builder = ExecutionSnapshotBuilder(canonical_root)
        self._root = snapshot_root
        self._ids = SequentialIdGenerator(prefix="snap")

    def provision(self, approved_read_scope: tuple[str, ...]) -> ProvisionedSnapshot:
        ref = self._ids.new_id()
        staging = self._root / ref
        try:
            snapshot = self._builder.build(approved_read_scope, staging)
        except SnapshotError:
            return ProvisionedSnapshot(SnapshotProvisionStatus.SETUP_FAILED)
        status = (
            SnapshotProvisionStatus.BUILT_VERIFIED
            if self._builder.verify(snapshot)
            else SnapshotProvisionStatus.INTEGRITY_MISMATCH
        )
        return ProvisionedSnapshot(
            status,
            snapshot_ref=ref,
            runtime_output_ref=f"out-{ref}",
            manifest_digest=snapshot.manifest.aggregate_digest,
            file_count=snapshot.manifest.file_count,
            total_bytes=snapshot.manifest.total_bytes,
        )

    def cleanup(self, snapshot: ProvisionedSnapshot) -> CleanupOutcome:
        if snapshot.snapshot_ref is None:
            return CleanupOutcome(CleanupStatus.CLEAN)
        cleanup_snapshot(self._root / snapshot.snapshot_ref, self._root)
        return CleanupOutcome(CleanupStatus.CLEAN)


def _shell(workspace: Path, docker: Path) -> SubprocessShellAdapter:
    scope = PathScope.build(read_roots=(workspace,), write_roots=())
    policy = CommandPolicy(
        (
            CommandRule(
                "docker",
                allowed_arg_prefixes=(("run",), ("rm",), ("image",), ("version",)),
                allow_trailing_args=True,
            ),
            CommandRule(
                "python", allowed_arg_prefixes=(("-m", "pytest"),), allow_trailing_args=True
            ),
        )
    )
    return SubprocessShellAdapter(
        config=BoundedShellConfig(
            workspace_root=workspace,
            trusted_executables={"docker": docker},
            output_limit=OutputLimit(65536),
        ),
        command_policy=policy,
        cwd_policy=PathPolicy(scope, workspace_root=workspace),
        redactor=Redactor(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="SH"),
    )


@pytest.fixture
def docker_ready() -> Path:
    docker = _docker()
    if docker is None or not docker.is_file():
        pytest.skip("docker CLI not available on host")
    if _run([str(docker), "image", "inspect", TEST_ISOLATION_IMAGE_REF]).returncode != 0:
        pytest.skip("pinned test image not present (no implicit pull)")
    probe = _run(
        [
            str(docker),
            "run",
            "--rm",
            TEST_ISOLATION_IMAGE_REF,
            "python",
            "-m",
            "pytest",
            "--version",
        ]
    )
    if probe.returncode != 0:
        pytest.skip("pytest not available inside the pinned image")
    return docker


def _ant(workspace: Path, docker: Path, tmp_path: Path) -> TestAnt:
    from ant_orchestrator.adapters.container_isolation import ContainerIsolationBackend

    snapshot_root = tmp_path / "snapshots"
    runtime_root = tmp_path / "runtime"
    snapshot_root.mkdir()
    runtime_root.mkdir()
    backend = ContainerIsolationBackend(
        shell=_shell(workspace, docker),
        resolver=_resolver(),
        snapshot_root=snapshot_root,
        runtime_root=runtime_root,
        audit_sink=FakeAuditSink(),
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="ISO"),
    )
    return TestAnt(
        command_registry=default_test_command_registry(),
        command_policy=_policy(),
        provisioner=_RealProvisioner(workspace, snapshot_root),
        isolation=backend,
        classifier=TestFailureClassifier(),
        clock=FakeClock(TS),
    )


def _policy() -> CommandPolicy:
    return CommandPolicy(
        (CommandRule("python", allowed_arg_prefixes=(("-m", "pytest"),), allow_trailing_args=True),)
    )


def _resolver() -> object:
    from ant_orchestrator.security.test_command_profile import TestCommandResolver

    return TestCommandResolver(default_test_command_registry(), _policy())


def _scope(workspace: Path) -> object:
    from ant_orchestrator.application.ports.test_worker import TestExecutionScope

    return TestExecutionScope(
        attempt_id="att-1",
        run_id="run-1",
        logical_action_id="t1-test",
        canonical_read_scope=("tests",),
        command_profile_key="pytest.acceptance",
        idempotency_key="idem-1",
    )


def _task() -> object:
    from ant_orchestrator.application.ports.test_worker import TestTask

    return TestTask(task_ref="t1", logical_action_id="t1-test", command_key="pytest.acceptance")


def test_acceptance_pass_end_to_end(docker_ready: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_smoke.py").write_text("def test_ok():\n    assert True\n", "utf-8")
    ant = _ant(workspace, docker_ready, tmp_path)
    result = ant.execute(_task(), _scope(workspace), "run-1")
    assert result.structured_report.test_result is TestResult.PASSED
    assert result.structured_report.is_success
    payload = json.dumps(result.structured_report.to_state_dict())
    assert str(workspace) not in payload and ":\\" not in payload  # no host absolute path
    assert result.structured_report.cleanup_status is CleanupStatus.CLEAN


def test_acceptance_failure_end_to_end(docker_ready: Path, tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_bad.py").write_text("def test_no():\n    assert False\n", "utf-8")
    ant = _ant(workspace, docker_ready, tmp_path)
    result = ant.execute(_task(), _scope(workspace), "run-1")
    assert result.structured_report.test_result is TestResult.FAILED
    assert not result.structured_report.is_success
    assert json.dumps(result.structured_report.to_state_dict()).count(str(tmp_path)) == 0
