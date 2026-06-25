"""CP4 bounded filesystem adapter tests: read, write, policy, audit, secrets."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.audit import AuditEventType
from ant_orchestrator.application.ports.filesystem import FileReadRequest, FileWriteRequest
from ant_orchestrator.application.ports.tool_errors import (
    ToolInvalidRequestError,
    ToolNotFoundError,
    ToolPermissionError,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.execution.bounded_fs import BoundedFileSystemAdapter, BoundedFsConfig
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.redaction.redactor import Redactor
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink


def _touch(p: Path, content: str = "hello") -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


def _adapter(
    tmp_path: Path,
    *,
    read: bool = True,
    write: bool = False,
    max_read: int = 65536,
    audit: FakeAuditSink | None = None,
) -> tuple[BoundedFileSystemAdapter, FakeAuditSink]:
    sink = audit or FakeAuditSink()
    r = (tmp_path,) if read else ()
    w = (tmp_path,) if write else ()
    scope = PathScope.build(read_roots=r, write_roots=w)
    return BoundedFileSystemAdapter(
        config=BoundedFsConfig(workspace_root=tmp_path, max_read_bytes=max_read),
        path_policy=PathPolicy(scope, workspace_root=tmp_path),
        redactor=Redactor(),
        audit_sink=sink,
        clock=FakeClock(UtcTimestamp(datetime(2026, 6, 25, tzinfo=UTC))),
        id_gen=SequentialIdGenerator(),
    ), sink


def _run_read(a: BoundedFileSystemAdapter, path: str) -> object:
    return asyncio.get_event_loop().run_until_complete(a.read_text(FileReadRequest(path=path)))


def _run_write(a: BoundedFileSystemAdapter, path: str, content: str) -> object:
    return asyncio.get_event_loop().run_until_complete(
        a.write_text(FileWriteRequest(path=path, content=content))
    )


# ------------------------------------------------------------------
# Read — allowed behavior
# ------------------------------------------------------------------


class TestReadAllowed:
    def test_read_in_scope(self, tmp_path: Path) -> None:
        _touch(tmp_path / "f.txt", "content")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "f.txt")
        assert r.content == "content"

    def test_read_nested(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a" / "b.txt", "deep")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "a/b.txt")
        assert r.content == "deep"

    def test_read_empty_file(self, tmp_path: Path) -> None:
        _touch(tmp_path / "e.txt", "")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "e.txt")
        assert r.content == ""

    def test_read_unicode_utf8(self, tmp_path: Path) -> None:
        _touch(tmp_path / "u.txt", "日本語")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "u.txt")
        assert "日本語" in r.content

    def test_read_crlf(self, tmp_path: Path) -> None:
        (tmp_path / "cr.txt").write_bytes(b"line1\r\nline2\r\n")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "cr.txt")
        assert "line1" in r.content


# ------------------------------------------------------------------
# Read — denial
# ------------------------------------------------------------------


class TestReadDenial:
    def test_outside_scope(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        _touch(tmp_path / "secret.txt")
        a, _ = _adapter(inner)
        with pytest.raises(ToolPermissionError):
            _run_read(a, str(tmp_path / "secret.txt"))

    def test_traversal(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        _touch(tmp_path / "up.txt")
        a, _ = _adapter(inner)
        with pytest.raises((ToolPermissionError, ToolNotFoundError)):
            _run_read(a, "../up.txt")

    def test_missing_file(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolNotFoundError):
            _run_read(a, "nope.txt")

    def test_directory_not_file(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolInvalidRequestError):
            _run_read(a, "dir")

    def test_write_scope_no_read(self, tmp_path: Path) -> None:
        _touch(tmp_path / "w.txt")
        a, _ = _adapter(tmp_path, read=False, write=True)
        with pytest.raises(ToolPermissionError):
            _run_read(a, "w.txt")


# ------------------------------------------------------------------
# Read — size / binary / encoding
# ------------------------------------------------------------------


class TestReadSizeBinary:
    def test_under_limit(self, tmp_path: Path) -> None:
        _touch(tmp_path / "s.txt", "x" * 50)
        a, _ = _adapter(tmp_path, max_read=100)
        r = _run_read(a, "s.txt")
        assert len(r.content) == 50

    def test_exact_limit(self, tmp_path: Path) -> None:
        _touch(tmp_path / "e.txt", "x" * 100)
        a, _ = _adapter(tmp_path, max_read=100)
        r = _run_read(a, "e.txt")
        assert len(r.content) == 100

    def test_over_limit(self, tmp_path: Path) -> None:
        _touch(tmp_path / "o.txt", "x" * 200)
        a, _ = _adapter(tmp_path, max_read=100)
        with pytest.raises(ToolInvalidRequestError):
            _run_read(a, "o.txt")

    def test_nul_byte_binary(self, tmp_path: Path) -> None:
        (tmp_path / "bin.dat").write_bytes(b"hello\x00world")
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolInvalidRequestError):
            _run_read(a, "bin.dat")

    def test_invalid_utf8(self, tmp_path: Path) -> None:
        (tmp_path / "bad.txt").write_bytes(b"\xff\xfe\x80")
        a, _ = _adapter(tmp_path)
        with pytest.raises(ToolInvalidRequestError):
            _run_read(a, "bad.txt")

    def test_valid_multibyte(self, tmp_path: Path) -> None:
        _touch(tmp_path / "mb.txt", "café résumé")
        a, _ = _adapter(tmp_path, max_read=100)
        r = _run_read(a, "mb.txt")
        assert "café" in r.content


# ------------------------------------------------------------------
# Read — secret redaction
# ------------------------------------------------------------------


class TestReadSecrets:
    def test_env_assignment(self, tmp_path: Path) -> None:
        _touch(tmp_path / "env.txt", "export DB_PASSWORD=mysecretpassword")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "env.txt")
        assert "mysecretpassword" not in r.content
        assert "[REDACTED]" in r.content

    def test_api_token(self, tmp_path: Path) -> None:
        _touch(tmp_path / "tok.txt", "key: sk-abcdef1234567890abcdefgh")
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "tok.txt")
        assert "sk-abcdef" not in r.content

    def test_pem_key(self, tmp_path: Path) -> None:
        pem = "-----BEGIN RSA PRIVATE KEY-----\ndata\n-----END RSA PRIVATE KEY-----"
        _touch(tmp_path / "k.pem", pem)
        a, _ = _adapter(tmp_path)
        r = _run_read(a, "k.pem")
        assert "BEGIN RSA PRIVATE KEY" not in r.content

    def test_audit_no_content(self, tmp_path: Path) -> None:
        _touch(tmp_path / "c.txt", "secret: password=hunter2")
        a, sink = _adapter(tmp_path)
        _run_read(a, "c.txt")
        for e in sink.events:
            for v in e.detail.values():
                assert "hunter2" not in v


# ------------------------------------------------------------------
# Write — allowed
# ------------------------------------------------------------------


class TestWriteAllowed:
    def test_create_new_file(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path, read=False, write=True)
        r = _run_write(a, "new.txt", "hello")
        assert r.changed is True
        assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hello"

    def test_overwrite_existing(self, tmp_path: Path) -> None:
        _touch(tmp_path / "ex.txt", "old")
        a, _ = _adapter(tmp_path, read=False, write=True)
        r = _run_write(a, "ex.txt", "new")
        assert r.changed is True
        assert (tmp_path / "ex.txt").read_text(encoding="utf-8") == "new"

    def test_same_content_unchanged(self, tmp_path: Path) -> None:
        _touch(tmp_path / "same.txt", "same")
        a, _ = _adapter(tmp_path, read=False, write=True)
        r = _run_write(a, "same.txt", "same")
        assert r.changed is False

    def test_unicode_content(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path, read=False, write=True)
        _run_write(a, "uni.txt", "日本語")
        assert (tmp_path / "uni.txt").read_text(encoding="utf-8") == "日本語"

    def test_empty_content(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path, read=False, write=True)
        r = _run_write(a, "empty.txt", "")
        assert r.changed is True

    def test_content_not_redacted(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path, read=False, write=True)
        secret = "export API_KEY=sk-abcdef1234567890abcdefgh"
        _run_write(a, "s.txt", secret)
        assert (tmp_path / "s.txt").read_text(encoding="utf-8") == secret


# ------------------------------------------------------------------
# Write — denial
# ------------------------------------------------------------------


class TestWriteDenial:
    def test_outside_write_scope(self, tmp_path: Path) -> None:
        inner = tmp_path / "inner"
        inner.mkdir()
        a, _ = _adapter(inner, read=False, write=True)
        with pytest.raises(ToolPermissionError):
            _run_write(a, str(tmp_path / "outside.txt"), "x")

    def test_read_scope_no_write(self, tmp_path: Path) -> None:
        _touch(tmp_path / "r.txt")
        a, _ = _adapter(tmp_path, read=True, write=False)
        with pytest.raises(ToolPermissionError):
            _run_write(a, "r.txt", "x")

    def test_target_is_directory(self, tmp_path: Path) -> None:
        (tmp_path / "dir").mkdir()
        a, _ = _adapter(tmp_path, read=False, write=True)
        with pytest.raises(ToolInvalidRequestError):
            _run_write(a, "dir", "x")

    def test_missing_parent(self, tmp_path: Path) -> None:
        a, _ = _adapter(tmp_path, read=False, write=True)
        with pytest.raises(ToolNotFoundError):
            _run_write(a, "no/parent/file.txt", "x")


# ------------------------------------------------------------------
# Write — side-effect protection
# ------------------------------------------------------------------


class TestWriteProtection:
    def test_deny_does_not_modify(self, tmp_path: Path) -> None:
        _touch(tmp_path / "keep.txt", "original")
        a, _ = _adapter(tmp_path, read=True, write=False)
        with pytest.raises(ToolPermissionError):
            _run_write(a, "keep.txt", "modified")
        assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "original"

    def test_pre_write_audit_failure_no_create(self, tmp_path: Path) -> None:
        class _FailAllow(FakeAuditSink):
            def write(self, event: object) -> None:
                if getattr(event, "decision", None) is PolicyDecision.ALLOW:
                    raise RuntimeError("audit fail")
                super().write(event)  # type: ignore[arg-type]

        a, _ = _adapter(tmp_path, read=False, write=True, audit=_FailAllow())
        with pytest.raises(RuntimeError):
            _run_write(a, "new.txt", "x")
        assert not (tmp_path / "new.txt").exists()

    def test_no_content_in_audit(self, tmp_path: Path) -> None:
        a, sink = _adapter(tmp_path, read=False, write=True)
        _run_write(a, "w.txt", "sensitive data 12345")
        for e in sink.events:
            for v in e.detail.values():
                assert "sensitive" not in v
                assert "12345" not in v


# ------------------------------------------------------------------
# Audit events
# ------------------------------------------------------------------


class TestAuditEvents:
    def test_read_emits_allow(self, tmp_path: Path) -> None:
        _touch(tmp_path / "a.txt")
        a, sink = _adapter(tmp_path)
        _run_read(a, "a.txt")
        allows = [e for e in sink.events if e.decision is PolicyDecision.ALLOW]
        assert len(allows) >= 1

    def test_deny_emits_deny(self, tmp_path: Path) -> None:
        a, sink = _adapter(tmp_path)
        with pytest.raises(ToolNotFoundError):
            _run_read(a, "nope.txt")
        denies = [e for e in sink.events if e.decision is PolicyDecision.DENY]
        assert len(denies) >= 1
        assert denies[0].event_type is AuditEventType.PATH_DECISION
