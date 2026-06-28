"""CP7 E2E Docker: real Docker integration with pytest-enabled fixture image.

Uses a pre-built local fixture image (ant-test-pytest-fixture:local) without
rebuilding or pulling from the network. Tests the full path:
DurableTestExecution → TestAnt → ContainerIsolationBackend → Docker container
→ structured outcome.

Skipped when Docker daemon is unavailable, the fixture image is absent, or
pytest is not found in the image. Skips are distinct: each has a specific reason.

CP7 deviation (§O): fixture image is test-only (ant-test-pytest-fixture:local).
Production TEST_ISOLATION_IMAGE_ID is unchanged. Wheel archives are not committed.
Build the image once offline: docker build -t ant-test-pytest-fixture:local \\
  tests/docker/pytest_fixture/  (requires network; run manually, not at test time).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.execution.bounded_shell import BoundedShellConfig, SubprocessShellAdapter
from ant_orchestrator.execution.output_limit import OutputLimit
from ant_orchestrator.execution.test_snapshot import (
    ExecutionSnapshotBuilder,
    SnapshotError,
    cleanup_snapshot,
)
from ant_orchestrator.integration.test_execution_adapter import DurableTestExecution
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.security.test_command_profile import (
    TestCommandResolver,
    default_test_command_registry,
)
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
from tests.support.cp7_e2e_harness import (
    PROFILE_KEY,
    RUN_ID,
    TASK_ID,
    fake_clock,
    make_db,
    make_orch,
)
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.phase3_harness import TS

_FIXTURE_TAG = "ant-test-pytest-fixture:local"
_READ_SCOPE = ("tests",)
_LOGICAL_ACTION_ID = f"{TASK_ID}-test"


def _docker() -> Path | None:
    found = shutil.which("docker")
    return Path(found) if found else None


def _run(argv: list[str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(argv, capture_output=True, timeout=120)


@pytest.fixture(scope="module")
def docker_fixture_image():
    """Locate the pre-built pytest fixture image and return (docker_path, image_id).

    Does NOT build or pull the image.  Three distinct skip reasons:
    - Docker daemon unavailable on host.
    - Fixture image absent (build once manually; see module docstring).
    - pytest not executable inside the image.
    """
    docker = _docker()
    if docker is None:
        pytest.skip("Docker daemon unavailable on host (docker CLI not found)")
    inspect = _run([str(docker), "image", "inspect", _FIXTURE_TAG, "--format", "{{.Id}}"])
    if inspect.returncode != 0:
        pytest.skip(
            f"Fixture image '{_FIXTURE_TAG}' not present locally. "
            "Build it once offline: "
            "docker build -t ant-test-pytest-fixture:local tests/docker/pytest_fixture/"
        )
    image_id = inspect.stdout.decode().strip()
    probe = _run([str(docker), "run", "--rm", _FIXTURE_TAG, "python", "-m", "pytest", "--version"])
    if probe.returncode != 0:
        pytest.skip(f"pytest not executable in fixture image {image_id[:16]}")
    return docker, image_id


class _RealProvisioner:
    """Wraps ExecutionSnapshotBuilder behind the TestSnapshotProvisioner port."""

    def __init__(self, workspace: Path, snapshot_root: Path) -> None:
        self._builder = ExecutionSnapshotBuilder(workspace)
        self._root = snapshot_root
        self._ids = SequentialIdGenerator(prefix="snap")

    def provision(self, approved_read_scope: tuple[str, ...]) -> ProvisionedSnapshot:
        ref = self._ids.new_id()
        staging = self._root / ref
        try:
            snap = self._builder.build(approved_read_scope, staging)
        except SnapshotError:
            return ProvisionedSnapshot(SnapshotProvisionStatus.SETUP_FAILED)
        status = (
            SnapshotProvisionStatus.BUILT_VERIFIED
            if self._builder.verify(snap)
            else SnapshotProvisionStatus.INTEGRITY_MISMATCH
        )
        return ProvisionedSnapshot(
            status,
            snapshot_ref=ref,
            runtime_output_ref=f"out-{ref}",
            manifest_digest=snap.manifest.aggregate_digest,
            file_count=snap.manifest.file_count,
            total_bytes=snap.manifest.total_bytes,
        )

    def cleanup(self, snapshot: ProvisionedSnapshot) -> CleanupOutcome:
        if snapshot.snapshot_ref is not None:
            cleanup_snapshot(self._root / snapshot.snapshot_ref, self._root)
        return CleanupOutcome(CleanupStatus.CLEAN)


def _build_ant(workspace: Path, docker: Path, image_id: str, tmp_path: Path) -> TestAnt:
    from ant_orchestrator.adapters.container_isolation import ContainerIsolationBackend

    snapshot_root = tmp_path / "snapshots"
    runtime_root = tmp_path / "runtime"
    snapshot_root.mkdir()
    runtime_root.mkdir()

    scope = PathScope.build(read_roots=(workspace,), write_roots=())
    cmd_policy = CommandPolicy(
        (
            CommandRule(
                "docker",
                allowed_arg_prefixes=(("run",), ("rm",), ("image",), ("version",)),
                allow_trailing_args=True,
            ),
            CommandRule(
                "python",
                allowed_arg_prefixes=(("-m", "pytest"),),
                allow_trailing_args=True,
            ),
        )
    )
    shell = SubprocessShellAdapter(
        config=BoundedShellConfig(
            workspace_root=workspace,
            trusted_executables={"docker": docker},
            output_limit=OutputLimit(65536),
        ),
        command_policy=cmd_policy,
        cwd_policy=PathPolicy(scope, workspace_root=workspace),
        redactor=Redactor(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="SH"),
    )
    resolver = TestCommandResolver(default_test_command_registry(), cmd_policy)
    backend = ContainerIsolationBackend(
        shell=shell,
        resolver=resolver,
        snapshot_root=snapshot_root,
        runtime_root=runtime_root,
        audit_sink=FakeAuditSink(),
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="ISO"),
        image_ref=image_id,
    )
    return TestAnt(
        command_registry=default_test_command_registry(),
        command_policy=cmd_policy,
        provisioner=_RealProvisioner(workspace, snapshot_root),
        isolation=backend,
        classifier=TestFailureClassifier(),
        clock=FakeClock(TS),
    )


def _build_durable(ant: TestAnt, orch) -> DurableTestExecution:
    return DurableTestExecution(
        ant=ant,
        attempt_orchestrator=orch,
        canonical_read_scope=_READ_SCOPE,
        command_profile_key=PROFILE_KEY,
    )


# ---------------------------------------------------------------------------
# S16: real Docker happy path (all tests pass)
# ---------------------------------------------------------------------------


def test_docker_pass_e2e(docker_fixture_image, tmp_path: Path) -> None:
    """S16: real Docker run — test passes → SUCCESS outcome, no host path in report."""
    docker, image_id = docker_fixture_image
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_pass.py").write_text(
        "def test_always_ok():\n    assert True\n", "utf-8"
    )

    c = fake_clock()
    db = make_db(tmp_path, c, TASK_ID, RUN_ID)
    orch = make_orch(db, c)
    ant = _build_ant(workspace, docker, image_id, tmp_path)
    durable = _build_durable(ant, orch)

    outcome = durable.execute(task_id=TASK_ID, run_id=RUN_ID)

    assert outcome.outcome is WorkerOutcome.SUCCESS
    assert outcome.attempt_ref != ""
    # No host absolute path in the attempt ref
    assert str(tmp_path) not in outcome.attempt_ref


def test_docker_pass_report_is_success(docker_fixture_image, tmp_path: Path) -> None:
    """S16b: Docker pass → structured report confirms TestResult.PASSED."""
    docker, image_id = docker_fixture_image
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_smoke.py").write_text(
        "def test_one():\n    assert 1 == 1\n", "utf-8"
    )

    c = fake_clock()
    db = make_db(tmp_path, c, TASK_ID, "DR2")
    orch = make_orch(db, c)
    ant = _build_ant(workspace, docker, image_id, tmp_path)

    from ant_orchestrator.application.ports.test_worker import TestExecutionScope, TestTask

    task = TestTask(task_ref=TASK_ID, logical_action_id=_LOGICAL_ACTION_ID, command_key=PROFILE_KEY)
    attempt_id = orch.before_execute("DR2", _LOGICAL_ACTION_ID)
    scope = TestExecutionScope(
        attempt_id=attempt_id,
        run_id="DR2",
        logical_action_id=_LOGICAL_ACTION_ID,
        canonical_read_scope=_READ_SCOPE,
        command_profile_key=PROFILE_KEY,
        idempotency_key=f"DR2\x00{_LOGICAL_ACTION_ID}\x00{attempt_id}",
    )
    result = ant.execute(task, scope, "DR2")
    assert result.structured_report.test_result is TestResult.PASSED


# ---------------------------------------------------------------------------
# S17: real Docker deterministic failure (tests fail)
# ---------------------------------------------------------------------------


def test_docker_fail_e2e(docker_fixture_image, tmp_path: Path) -> None:
    """S17: real Docker run — test fails → non-SUCCESS outcome."""
    docker, image_id = docker_fixture_image
    workspace = tmp_path / "ws"
    (workspace / "tests").mkdir(parents=True)
    (workspace / "tests" / "test_fail.py").write_text(
        "def test_always_bad():\n    assert False, 'deterministic failure'\n", "utf-8"
    )

    c = fake_clock()
    db = make_db(tmp_path, c, TASK_ID, "DR3")
    orch = make_orch(db, c)
    ant = _build_ant(workspace, docker, image_id, tmp_path)
    durable = DurableTestExecution(
        ant=ant,
        attempt_orchestrator=orch,
        canonical_read_scope=_READ_SCOPE,
        command_profile_key=PROFILE_KEY,
    )

    outcome = durable.execute(task_id=TASK_ID, run_id="DR3")

    assert outcome.outcome is not WorkerOutcome.SUCCESS
    assert outcome.attempt_ref != ""
