"""CP5 — version contract and antctl/ant entry point tests."""

from __future__ import annotations

import os
import subprocess
import sysconfig
from pathlib import Path

from ant_orchestrator.config.constants import ANT_CLI_VERSION


def _exe(name: str) -> Path:
    scripts_dir = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"{name}{suffix}"


class TestVersionConstant:
    def test_version_is_semver(self) -> None:
        parts = ANT_CLI_VERSION.split(".")
        assert len(parts) == 3, f"Expected semver x.y.z, got {ANT_CLI_VERSION!r}"
        for part in parts:
            assert part.isdigit(), f"Non-numeric semver part {part!r}"

    def test_version_is_0_1_0(self) -> None:
        assert ANT_CLI_VERSION == "0.1.0"


class TestAntctlEntryPoint:
    def test_antctl_executable_exists(self) -> None:
        exe = _exe("antctl")
        assert exe.exists(), f"antctl not found at {exe}. Run: pip install -e '.[dev]'"

    def test_antctl_version(self) -> None:
        exe = _exe("antctl")
        assert exe.exists(), f"antctl not found at {exe}"
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert ANT_CLI_VERSION in result.stdout

    def test_antctl_help_runs(self) -> None:
        exe = _exe("antctl")
        assert exe.exists(), f"antctl not found at {exe}"
        result = subprocess.run(
            [str(exe), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0
        assert "Usage" in result.stdout

    def test_antctl_outside_workspace(self, tmp_path: Path) -> None:
        """--version should work from any directory without a workspace."""
        exe = _exe("antctl")
        assert exe.exists()
        result = subprocess.run(
            [str(exe), "--version"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0
        assert ANT_CLI_VERSION in result.stdout


class TestAntLegacyEntryPoint:
    def test_ant_executable_exists(self) -> None:
        exe = _exe("ant")
        assert exe.exists(), f"ant not found at {exe}. Run: pip install -e '.[dev]'"

    def test_ant_version_same_as_antctl(self) -> None:
        ant = _exe("ant")
        antctl = _exe("antctl")
        assert ant.exists() and antctl.exists()
        r1 = subprocess.run([str(antctl), "--version"], capture_output=True, text=True, check=False)
        r2 = subprocess.run([str(ant), "--version"], capture_output=True, text=True, check=False)
        assert r1.returncode == 0 and r2.returncode == 0
        assert r1.stdout == r2.stdout

    def test_ant_help_same_commands(self) -> None:
        ant = _exe("ant")
        antctl = _exe("antctl")
        assert ant.exists() and antctl.exists()
        r1 = subprocess.run([str(antctl), "--help"], capture_output=True, text=True, check=False)
        r2 = subprocess.run([str(ant), "--help"], capture_output=True, text=True, check=False)
        assert r1.returncode == 0 and r2.returncode == 0
        # Both must expose the same set of commands (doctor, configure, task, etc.)
        for cmd in ("doctor", "configure", "task", "run", "approve", "reject", "cancel"):
            assert cmd in r1.stdout, f"antctl missing command: {cmd}"
            assert cmd in r2.stdout, f"ant missing command: {cmd}"
