"""Deterministic Docker argv construction for Test Ant isolation (PHASE_6_PLAN CP2, §3.3).

Pure functions: given a fully-resolved, typed launch plan they return the exact ``docker``
argv. The worker NEVER supplies Docker argv, mounts, environment or executable — the
backend builds every token here. ``--mount type=bind`` is used (not ``-v``) so a Windows
host path with a drive ``:`` is unambiguous. No subprocess, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ant_orchestrator.core.domain.errors import InvariantViolation

_DOCKER = "docker"


@dataclass(frozen=True, slots=True)
class ContainerRunPlan:
    """Fully-resolved, typed inputs for one ``docker run`` invocation."""

    name: str
    image_ref: str
    snapshot_host: str
    out_host: str
    inner_argv: tuple[str, ...]
    user: str
    pids_limit: int
    memory: str
    tmpfs_size: str
    work_mount: str
    out_mount: str
    network_disabled: bool = True
    env: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for name in ("name", "image_ref", "snapshot_host", "out_host", "user"):
            if not getattr(self, name):
                raise InvariantViolation(f"ContainerRunPlan.{name} must be non-empty")
        if not self.inner_argv or not self.inner_argv[0].strip():
            raise InvariantViolation("ContainerRunPlan.inner_argv must start with an executable")
        if self.pids_limit <= 0:
            raise InvariantViolation("ContainerRunPlan.pids_limit must be > 0")
        for key, _ in self.env:
            if not key or "=" in key:
                raise InvariantViolation("ContainerRunPlan.env key must be a bare NAME")


def build_run_argv(plan: ContainerRunPlan) -> tuple[str, ...]:
    """Return the deterministic, least-privilege ``docker run`` argv."""
    argv: list[str] = [
        _DOCKER,
        "run",
        "--name",
        plan.name,
        "--read-only",
        "--user",
        plan.user,
        "--pids-limit",
        str(plan.pids_limit),
        "--memory",
        plan.memory,
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
    ]
    if plan.network_disabled:
        argv += ["--network", "none"]
    argv += [
        "--mount",
        f"type=bind,source={plan.snapshot_host},target={plan.work_mount},readonly",
        "--mount",
        f"type=bind,source={plan.out_host},target={plan.out_mount}",
        "--tmpfs",
        f"/tmp:rw,size={plan.tmpfs_size}",
        "-w",
        plan.work_mount,
    ]
    for key, value in plan.env:
        argv += ["--env", f"{key}={value}"]
    argv.append(plan.image_ref)
    argv.extend(plan.inner_argv)
    return tuple(argv)


def build_remove_argv(name: str) -> tuple[str, ...]:
    """Return the idempotent force-remove argv for a container by name."""
    if not name:
        raise InvariantViolation("container name must be non-empty")
    return (_DOCKER, "rm", "-f", name)


def build_version_argv() -> tuple[str, ...]:
    """Return the daemon-reachability probe argv."""
    return (_DOCKER, "version")


def build_image_inspect_argv(image_ref: str) -> tuple[str, ...]:
    """Return the image-identity (digest-pinned) presence probe argv."""
    if not image_ref:
        raise InvariantViolation("image_ref must be non-empty")
    return (_DOCKER, "image", "inspect", image_ref)
