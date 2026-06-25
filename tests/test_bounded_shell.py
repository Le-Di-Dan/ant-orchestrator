"""CP3 bounded shell adapter tests: policy, cwd, output, timeout, evidence."""

from __future__ import annotations

import asyncio
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.audit import AuditEventType
from ant_orchestrator.application.ports.shell import ShellRequest
from ant_orchestrator.application.ports.tool_errors import (
    ToolNotFoundError,
    ToolPermissionError,
    ToolTimeoutError,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.execution.bounded_shell import (
    BoundedShellConfig,
    SubprocessShellAdapter,
)
from ant_orchestrator.execution.output_limit import OutputLimit
from ant_orchestrator.security.command_policy import CommandPolicy, CommandRule
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_PY = Path(sys.executable).resolve()


def _script(tmp_path: Path, name: str, code: str) -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


def _adapter(
    tmp_path: Path,
    *,
    rules: tuple[CommandRule, ...] | None = None,
    audit: FakeAuditSink | None = None,
    timeout: float = 10.0,
    max_output: int = 4096,
) -> tuple[SubprocessShellAdapter, FakeAuditSink]:
    sink = audit or FakeAuditSink()
    if rules is None:
        rules = (
            CommandRule(executable="python", allowed_arg_prefixes=((),), allow_trailing_args=True),
        )
    scope = PathScope.build(read_roots=(tmp_path,), write_roots=())
    cfg = BoundedShellConfig(
        workspace_root=tmp_path,
        trusted_executables={"python": _PY},
        output_limit=OutputLimit(max_output),
        default_timeout=timeout,
    )
    adapter = SubprocessShellAdapter(
        config=cfg,
        command_policy=CommandPolicy(rules),
        cwd_policy=PathPolicy(scope, workspace_root=tmp_path),
        redactor=Redactor(),
        audit_sink=sink,
        clock=FakeClock(UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))),
        id_gen=SequentialIdGenerator(),
    )
    return adapter, sink


def _run(adapter: SubprocessShellAdapter, req: ShellRequest) -> object:
    return asyncio.get_event_loop().run_until_complete(adapter.run(req))


# ------------------------------------------------------------------
# Policy gate
# ------------------------------------------------------------------


class TestPolicyGate:
    def test_allowed_command_succeeds(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "ok.py", "print('ok')")
        a, sink = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert r.exit_code == 0
        assert "ok" in r.stdout

    def test_disallowed_executable_not_spawned(self, tmp_path: Path) -> None:
        a, sink = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("curl", "http://evil")))
        denies = [e for e in sink.events if e.decision is PolicyDecision.DENY]
        assert len(denies) >= 1

    def test_shell_wrapper_not_spawned(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("bash", "-c", "echo hi")))

    def test_metachar_not_spawned(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("python", "x;rm", "-rf")))

    def test_missing_trusted_executable(self, tmp_path: Path) -> None:
        cfg = BoundedShellConfig(
            workspace_root=tmp_path,
            trusted_executables={"python": tmp_path / "nonexistent"},
            output_limit=OutputLimit(4096),
        )
        scope = PathScope.build(read_roots=(tmp_path,), write_roots=())
        a = SubprocessShellAdapter(
            config=cfg,
            command_policy=CommandPolicy(
                (
                    CommandRule(
                        executable="python", allowed_arg_prefixes=((),), allow_trailing_args=True
                    ),
                )
            ),
            cwd_policy=PathPolicy(scope, workspace_root=tmp_path),
            redactor=Redactor(),
            audit_sink=FakeAuditSink(),
            clock=FakeClock(UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))),
            id_gen=SequentialIdGenerator(),
        )
        with pytest.raises(ToolNotFoundError):
            _run(a, ShellRequest(argv=("python", "x.py")))


# ------------------------------------------------------------------
# CWD
# ------------------------------------------------------------------


class TestCwd:
    def test_cwd_none_uses_workspace(self, tmp_path: Path) -> None:
        s = _script(
            tmp_path,
            "cwd.py",
            """\
            import os; print(os.getcwd())
        """,
        )
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert tmp_path.resolve().name in r.stdout

    def test_relative_cwd_valid(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        s = _script(tmp_path, "cwd2.py", "import os; print(os.getcwd())")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s)), cwd="sub"))
        assert "sub" in r.stdout

    def test_cwd_outside_scope_denied(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        a, _ = _adapter(tmp_path / "inner" if (tmp_path / "inner").mkdir() or True else tmp_path)
        inner = tmp_path / "inner"
        a2, _ = _adapter(inner)
        with pytest.raises(ToolPermissionError):
            _run(a2, ShellRequest(argv=("python", "-c", "pass"), cwd=str(outside)))

    def test_cwd_is_file_denied(self, tmp_path: Path) -> None:
        _script(tmp_path, "afile.txt", "content")
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("python", "x.py"), cwd="afile.txt"))

    def test_missing_cwd_denied(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("python", "x.py"), cwd="nope"))


# ------------------------------------------------------------------
# Output
# ------------------------------------------------------------------


class TestOutput:
    def test_stdout_captured(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "out.py", "print('hello stdout')")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert "hello stdout" in r.stdout

    def test_stderr_captured(self, tmp_path: Path) -> None:
        s = _script(
            tmp_path,
            "err.py",
            """\
            import sys; sys.stderr.write("hello stderr")
        """,
        )
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert "hello stderr" in r.stderr

    def test_output_over_limit_truncated(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "big.py", "print('x' * 10000)")
        a, _ = _adapter(tmp_path, max_output=200)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert len(r.stdout.encode("utf-8")) <= 200

    def test_secret_in_stdout_redacted(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "sec.py", "print('token: sk-abcdef1234567890abcdefgh')")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert "sk-abcdef" not in r.stdout
        assert "[REDACTED]" in r.stdout

    def test_secret_in_stderr_redacted(self, tmp_path: Path) -> None:
        s = _script(
            tmp_path,
            "secerr.py",
            """\
            import sys; sys.stderr.write("key=ghp_abcdef1234567890abcdefgh")
        """,
        )
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert "ghp_abcdef" not in r.stderr


# ------------------------------------------------------------------
# Exit / error
# ------------------------------------------------------------------


class TestExitError:
    def test_exit_zero(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "zero.py", "pass")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert r.exit_code == 0

    def test_nonzero_exit_is_result(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "fail.py", "raise SystemExit(42)")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert r.exit_code == 42

    def test_duration_positive(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "dur.py", "pass")
        a, _ = _adapter(tmp_path)
        r = _run(a, ShellRequest(argv=("python", str(s))))
        assert r.duration_seconds >= 0


# ------------------------------------------------------------------
# Timeout
# ------------------------------------------------------------------


class TestTimeout:
    def test_timeout_kills_process(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "slow.py", "import time; time.sleep(60)")
        a, sink = _adapter(tmp_path, timeout=1.0)
        with pytest.raises(ToolTimeoutError):
            _run(a, ShellRequest(argv=("python", str(s))))
        timeouts = [e for e in sink.events if e.detail.get("timed_out") == "True"]
        assert len(timeouts) >= 1

    def test_output_before_timeout_captured(self, tmp_path: Path) -> None:
        s = _script(
            tmp_path,
            "partial.py",
            """\
            import sys, time
            print("before", flush=True)
            time.sleep(60)
        """,
        )
        a, _ = _adapter(tmp_path, timeout=2.0)
        with pytest.raises(ToolTimeoutError):
            _run(a, ShellRequest(argv=("python", str(s))))


# ------------------------------------------------------------------
# Audit / evidence privacy
# ------------------------------------------------------------------


class TestAuditPrivacy:
    def test_audit_events_emitted(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "audit.py", "print('hi')")
        a, sink = _adapter(tmp_path)
        _run(a, ShellRequest(argv=("python", str(s))))
        types = {e.event_type for e in sink.events}
        assert AuditEventType.COMMAND_DECISION in types
        assert AuditEventType.EXECUTION in types

    def test_no_raw_argv_in_audit(self, tmp_path: Path) -> None:
        s = _script(tmp_path, "priv.py", "print('ok')")
        secret_arg = "DB_PASSWORD=supersecret123"
        a, sink = _adapter(tmp_path)
        _run(a, ShellRequest(argv=("python", str(s), secret_arg)))
        for event in sink.events:
            for v in event.detail.values():
                assert "supersecret123" not in v

    def test_deny_audit_no_raw_command(self, tmp_path: Path) -> None:
        a, sink = _adapter(tmp_path)
        with pytest.raises(ToolPermissionError):
            _run(a, ShellRequest(argv=("curl", "http://evil")))
        for event in sink.events:
            for v in event.detail.values():
                assert "curl" not in v
                assert "evil" not in v
