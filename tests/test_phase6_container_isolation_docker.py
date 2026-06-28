"""CP2 — REAL Docker isolation enforcement (gated; runs only when Docker is available).

These tests exercise the actual container boundary on the host: a digest-pinned image,
read-only snapshot mount, writable runtime mount, read-only rootfs, no network, non-root
user, child-process containment, and timeout-kills-the-container. They are skipped with a
clear reason where Docker is absent, but the production backend always fails closed.

Probes are real ``.py`` files materialized into the read-only snapshot and run as
``python <probe>.py``; they write their findings to the writable ``/out`` mount, which the
host then reads back for assertions. No probe argv contains a shell metacharacter.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from ant_orchestrator.adapters.container_isolation import ContainerIsolationBackend
from ant_orchestrator.application.ports.test_isolation import (
    IsolatedExecutionSpec,
    IsolatedRunStatus,
)
from ant_orchestrator.execution.bounded_shell import BoundedShellConfig, SubprocessShellAdapter
from ant_orchestrator.execution.output_limit import OutputLimit
from ant_orchestrator.execution.test_snapshot import ExecutionSnapshotBuilder
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.security.test_command_profile import (
    TestCommandKind,
    TestCommandProfile,
    TestCommandRegistry,
    TestCommandResolver,
)
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.support.phase3_harness import TS

_ENFORCE = """import os, socket, json
r = {}
r["read_work"] = open("/work/sample.txt").read().strip()
try:
    open("/work/evil.txt", "w").write("x")
    r["work_write"] = "ALLOWED_BAD"
except OSError:
    r["work_write"] = "denied"
try:
    open("/out/ok.txt", "w").write("ok")
    r["out_write"] = "ok"
except OSError:
    r["out_write"] = "FAIL"
try:
    open("/evil_rootfs", "w").write("x")
    r["rootfs"] = "ALLOWED_BAD"
except OSError:
    r["rootfs"] = "denied"
r["uid"] = os.getuid()
r["git_present"] = os.path.exists("/work/.git")
try:
    socket.create_connection(("1.1.1.1", 53), timeout=3)
    r["net"] = "REACHABLE_BAD"
except OSError:
    r["net"] = "denied"
open("/out/result.json", "w").write(json.dumps(r))
"""

_CHILD = """import subprocess, json
p = subprocess.run(
    ["python", "-c", "open('/work/evil_child.txt','w').write('x')"], capture_output=True
)
open("/out/child.json", "w").write(json.dumps({"rc": p.returncode}))
"""

_SLEEP = "import time\ntime.sleep(120)\n"


def _docker_path() -> Path | None:
    found = shutil.which("docker")
    return Path(found) if found else None


def _docker_image_present(docker: Path, image_ref: str) -> bool:
    try:
        proc = subprocess.run(
            [str(docker), "image", "inspect", image_ref],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def _command_policy() -> CommandPolicy:
    return CommandPolicy(
        (
            CommandRule(
                "docker",
                allowed_arg_prefixes=(("run",), ("rm",), ("image",), ("version",)),
                allow_trailing_args=True,
            ),
            CommandRule("python", allowed_arg_prefixes=((),), allow_trailing_args=True),
        )
    )


def _real_shell(workspace: Path, docker: Path, audit: FakeAuditSink) -> SubprocessShellAdapter:
    scope = PathScope.build(read_roots=(workspace,), write_roots=())
    return SubprocessShellAdapter(
        config=BoundedShellConfig(
            workspace_root=workspace,
            trusted_executables={"docker": docker},
            output_limit=OutputLimit(65536),
        ),
        command_policy=_command_policy(),
        cwd_policy=PathPolicy(scope, workspace_root=workspace),
        redactor=Redactor(),
        audit_sink=audit,
        clock=FakeClock(TS),
        id_gen=SequentialIdGenerator(prefix="SH"),
    )


def _registry() -> TestCommandRegistry:
    diag = TestCommandKind.DIAGNOSTIC
    return TestCommandRegistry(
        (
            TestCommandProfile("probe.enforce", diag, ("python", "probe_enforce.py"), 1),
            TestCommandProfile("probe.child", diag, ("python", "probe_child.py"), 1),
            TestCommandProfile("probe.sleep", diag, ("python", "probe_sleep.py"), 1),
        )
    )


class _Harness:
    def __init__(self, tmp_path: Path, docker: Path) -> None:
        self.canonical = tmp_path / "canonical"
        self.canonical.mkdir()
        (self.canonical / ".git").mkdir()
        (self.canonical / ".git" / "config").write_text("[core]\n", encoding="utf-8")
        (self.canonical / "sample.txt").write_text("hello-canonical-bytes", encoding="utf-8")
        (self.canonical / "probe_enforce.py").write_text(_ENFORCE, encoding="utf-8")
        (self.canonical / "probe_child.py").write_text(_CHILD, encoding="utf-8")
        (self.canonical / "probe_sleep.py").write_text(_SLEEP, encoding="utf-8")
        self.snapshot_root = tmp_path / "snapshots"
        self.runtime_root = tmp_path / "runtime"
        self.audit = FakeAuditSink()
        self._shell = _real_shell(tmp_path, docker, self.audit)
        self._resolver = TestCommandResolver(_registry(), _command_policy())
        self.staging = self.snapshot_root / "snap1"
        ExecutionSnapshotBuilder(self.canonical).build(
            ("sample.txt", "probe_enforce.py", "probe_child.py", "probe_sleep.py"), self.staging
        )

    def backend(self, timeout: float = 120.0) -> ContainerIsolationBackend:
        return ContainerIsolationBackend(
            shell=self._shell,
            resolver=self._resolver,
            snapshot_root=self.snapshot_root,
            runtime_root=self.runtime_root,
            audit_sink=self.audit,
            clock=FakeClock(TS),
            id_gen=SequentialIdGenerator(prefix="ISO"),
            timeout_seconds=timeout,
        )

    def out(self, ref: str, name: str) -> dict[str, object]:
        text = (self.runtime_root / ref / name).read_text(encoding="utf-8")
        data: dict[str, object] = json.loads(text)
        return data


def _spec(command_key: str, out_ref: str) -> IsolatedExecutionSpec:
    return IsolatedExecutionSpec(
        snapshot_ref="snap1",
        runtime_output_ref=out_ref,
        command_profile_key=command_key,
        timeout_ms=120_000,
        max_processes=256,
    )


@pytest.fixture
def harness(tmp_path: Path) -> _Harness:
    docker = _docker_path()
    if docker is None or not docker.is_file():
        pytest.skip("docker CLI not available on host")
    from ant_orchestrator.config.constants import TEST_ISOLATION_IMAGE_REF

    if not _docker_image_present(docker, TEST_ISOLATION_IMAGE_REF):
        pytest.skip("pinned test image not present (no implicit pull)")
    return _Harness(tmp_path, docker)


def test_capability_available_on_this_host(harness: _Harness) -> None:
    assert harness.backend().capability().is_available


def test_enforcement_invariants(harness: _Harness) -> None:
    canonical_digest = hashlib.sha256((harness.canonical / "sample.txt").read_bytes()).hexdigest()
    result = harness.backend().run(_spec("probe.enforce", "o1"))
    assert result.status is IsolatedRunStatus.COMPLETED
    r = harness.out("o1", "result.json")
    assert r["read_work"] == "hello-canonical-bytes"  # exact-byte snapshot at /work
    assert r["work_write"] == "denied"  # read-only snapshot mount
    assert r["out_write"] == "ok"  # writable runtime mount
    assert r["rootfs"] == "denied"  # read-only rootfs
    assert r["uid"] != 0  # non-root
    assert r["git_present"] is False  # .git not mounted
    assert r["net"] == "denied"  # network disabled
    # Canonical source is untouched and the read-only write never reached the snapshot.
    assert not (harness.staging / "evil.txt").exists()
    assert (
        hashlib.sha256((harness.canonical / "sample.txt").read_bytes()).hexdigest()
        == canonical_digest
    )
    assert (harness.runtime_root / "o1" / "ok.txt").exists()


def test_child_process_is_contained(harness: _Harness) -> None:
    result = harness.backend().run(_spec("probe.child", "o2"))
    assert result.status is IsolatedRunStatus.COMPLETED
    assert harness.out("o2", "child.json")["rc"] != 0  # child write to /work denied
    assert not (harness.staging / "evil_child.txt").exists()


def test_timeout_terminates_container(harness: _Harness) -> None:
    result = harness.backend(timeout=5.0).run(_spec("probe.sleep", "o3"))
    assert result.status is IsolatedRunStatus.TIMEOUT
    # No ant-test container is left running/existing after the bounded cleanup.
    docker = _docker_path()
    assert docker is not None
    listed = subprocess.run(
        [str(docker), "ps", "-aq", "--filter", "name=ant-test-"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert listed.stdout.strip() == ""
