"""Subprocess harness for the CP8 full-restart E2E suite (test-only).

Runs each step as a *real* OS process via ``sys.executable`` (never ``shell=True``,
never an in-process runner), captures exit code + stdout + stderr with a finite
timeout, and surfaces both streams when a step fails. Two entry points are exposed:

* :func:`run_cli` — the production ``ant`` console script (public CLI evidence).
* :func:`run_driver` — the test-only ``tests.support.cp8_driver`` module
  (application-service evidence for branches the vanilla CLI cannot reach).

Windows-safe: resolves the interpreter's console-scripts dir (no PATH assumption),
passes explicit ``--path``/``--workspace`` (no cwd-relative discovery), and uses
only ``pathlib`` paths.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import sysconfig
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True, slots=True)
class Proc:
    """The captured result of one subprocess step."""

    returncode: int
    stdout: str
    stderr: str

    def json(self) -> dict[str, object]:
        """Parse stdout as exactly one JSON document."""
        return json.loads(self.stdout)


def ant_exe() -> Path:
    """Resolve the installed ``ant`` console script for the running interpreter."""
    scripts_dir = Path(sysconfig.get_path("scripts"))
    name = "ant.exe" if os.name == "nt" else "ant"
    return scripts_dir / name


def _run(argv: list[str], *, timeout: float) -> Proc:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(REPO_ROOT) + (os.pathsep + existing if existing else "")
    try:
        completed = subprocess.run(
            argv,
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:  # pragma: no cover - timing dependent
        out = exc.stdout or ""
        err = exc.stderr or ""
        raise AssertionError(
            f"subprocess timed out after {timeout}s: {argv}\nstdout:\n{out}\nstderr:\n{err}"
        ) from exc
    return Proc(completed.returncode, completed.stdout, completed.stderr)


def run_cli(args: list[str], *, timeout: float = DEFAULT_TIMEOUT) -> Proc:
    """Run the production ``ant`` console script with ``args``."""
    exe = ant_exe()
    assert exe.exists(), f"ant console script missing at {exe}; run 'pip install -e .[dev]'"
    return _run([str(exe), *args], timeout=timeout)


def run_driver(args: list[str], *, timeout: float = DEFAULT_TIMEOUT) -> Proc:
    """Run the test-only application-service driver module with ``args``."""
    return _run([sys.executable, "-m", "tests.support.cp8_driver", *args], timeout=timeout)


# ---------------------------------------------------------------------------
# Convenience wrappers (each is one real process)
# ---------------------------------------------------------------------------


def init_nest(workspace: Path, *, timeout: float = DEFAULT_TIMEOUT) -> Proc:
    """``ant init --path <workspace>`` — provision the ``.ant/`` Nest."""
    return run_cli(["init", "--path", str(workspace)], timeout=timeout)


def cli_create_task(workspace: Path, *, title: str = "cp8 task", json_out: bool = True) -> Proc:
    """``ant task create`` against ``workspace`` (JSON by default)."""
    args = ["task", "create", "--title", title, "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def cli_run(workspace: Path, task_id: str, *, json_out: bool = True) -> Proc:
    """``ant run <task_id>`` against ``workspace``."""
    args = ["run", task_id, "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def cli_status(workspace: Path, *, json_out: bool = True) -> Proc:
    """``ant status`` against ``workspace``."""
    args = ["status", "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def cli_approve(workspace: Path, task_id: str, *, json_out: bool = True) -> Proc:
    """``ant approve <task_id>`` against ``workspace``."""
    args = ["approve", task_id, "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def cli_reject(workspace: Path, task_id: str, *, reason: str = "no", json_out: bool = True) -> Proc:
    """``ant reject <task_id> --reason ...`` against ``workspace``."""
    args = ["reject", task_id, "--reason", reason, "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def cli_cancel(workspace: Path, task_id: str, *, json_out: bool = True) -> Proc:
    """``ant cancel <task_id>`` against ``workspace``."""
    args = ["cancel", task_id, "--path", str(workspace)]
    if json_out:
        args.append("--json")
    return run_cli(args)


def init_and_create(workspace: Path, *, title: str = "cp8 task") -> str:
    """Init the Nest and create one task via the public CLI; return the task id."""
    init_proc = init_nest(workspace)
    assert init_proc.returncode == 0, _fmt("init", init_proc)
    created = cli_create_task(workspace, title=title)
    assert created.returncode == 0, _fmt("task create", created)
    task_id = created.json()["task_id"]
    assert isinstance(task_id, str) and task_id
    return task_id


def driver(
    command: str,
    workspace: Path,
    *,
    task_id: str | None = None,
    extra: list[str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> Proc:
    """Run one ``cp8_driver`` command against ``workspace``."""
    args = [command, "--workspace", str(workspace)]
    if task_id is not None:
        args += ["--task-id", task_id]
    if extra:
        args += extra
    return run_driver(args, timeout=timeout)


def _fmt(step: str, proc: Proc) -> str:
    return f"{step} failed (exit {proc.returncode})\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"


def expect_ok(step: str, proc: Proc) -> dict[str, object]:
    """Assert a step exited 0 and return its parsed JSON payload."""
    assert proc.returncode == 0, _fmt(step, proc)
    return proc.json()
