"""CP2 — deterministic Docker argv construction (pure, no Docker)."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from ant_orchestrator.adapters.container_argv import (
    ContainerRunPlan,
    build_image_inspect_argv,
    build_remove_argv,
    build_run_argv,
    build_version_argv,
)
from ant_orchestrator.core.domain.errors import InvariantViolation

_BASE = ContainerRunPlan(
    name="ant-test-abc",
    image_ref="python@sha256:deadbeef",
    snapshot_host=r"C:\snap",
    out_host=r"C:\out",
    inner_argv=("python", "-m", "pytest"),
    user="1000:1000",
    pids_limit=256,
    memory="512m",
    tmpfs_size="64m",
    work_mount="/work",
    out_mount="/out",
)


def _plan(**over: Any) -> ContainerRunPlan:
    return dataclasses.replace(_BASE, **over)


def test_run_argv_enforces_least_privilege_flags() -> None:
    argv = build_run_argv(_plan(env=(("HOME", "/out"),)))
    assert argv[0] == "docker" and argv[1] == "run"
    assert "--read-only" in argv
    assert ("--user", "1000:1000") == (argv[argv.index("--user")], argv[argv.index("--user") + 1])
    assert "--cap-drop" in argv and "ALL" in argv
    assert ("--security-opt" in argv) and ("no-new-privileges" in argv)
    assert ("--pids-limit" in argv) and ("--memory" in argv)
    assert ["--network", "none"] == [
        argv[argv.index("--network")],
        argv[argv.index("--network") + 1],
    ]


def test_run_argv_mounts_snapshot_readonly_and_out_writable() -> None:
    argv = build_run_argv(_plan())
    mounts = [argv[i + 1] for i, t in enumerate(argv) if t == "--mount"]
    work = next(m for m in mounts if "target=/work" in m)
    out = next(m for m in mounts if "target=/out" in m)
    assert work.endswith("readonly") and "source=C:\\snap" in work
    assert "readonly" not in out and "source=C:\\out" in out


def test_run_argv_has_no_dangerous_flags_and_image_then_inner_last() -> None:
    argv = build_run_argv(_plan())
    # Token-level checks (substring would false-match e.g. --pids-limit).
    for forbidden in ("--privileged", "--pid", "host", "--cap-add", "-v"):
        assert forbidden not in argv
    joined = " ".join(argv)
    assert "docker.sock" not in joined
    assert "/.git" not in joined
    image_idx = argv.index("python@sha256:deadbeef")
    assert argv[image_idx + 1 :] == ("python", "-m", "pytest")


def test_run_argv_can_disable_network_flag_only_when_requested() -> None:
    argv = build_run_argv(_plan(network_disabled=False))
    assert "--network" not in argv


def test_tmpfs_present_and_workdir_is_logical() -> None:
    argv = build_run_argv(_plan())
    assert "--tmpfs" in argv
    assert ["-w", "/work"] == [argv[argv.index("-w")], argv[argv.index("-w") + 1]]


def test_plan_rejects_bad_inputs() -> None:
    with pytest.raises(InvariantViolation):
        _plan(inner_argv=())
    with pytest.raises(InvariantViolation):
        _plan(pids_limit=0)
    with pytest.raises(InvariantViolation):
        _plan(name="")
    with pytest.raises(InvariantViolation):
        _plan(env=(("BAD=KEY", "v"),))


def test_lifecycle_argvs() -> None:
    assert build_remove_argv("ant-test-x") == ("docker", "rm", "-f", "ant-test-x")
    assert build_version_argv() == ("docker", "version")
    assert build_image_inspect_argv("img@sha256:1") == (
        "docker",
        "image",
        "inspect",
        "img@sha256:1",
    )
    with pytest.raises(InvariantViolation):
        build_remove_argv("")
