"""FakeGitReadAdapter contract conformance + read-only structural proof (CP5)."""

from __future__ import annotations

import asyncio

import pytest

from ant_orchestrator.application.ports.git_read import (
    ChangeKind,
    GitChange,
    GitDiffResult,
    GitReadAdapter,
    GitStatusRequest,
    GitStatusResult,
)
from ant_orchestrator.application.ports.tool_common import ToolInvocationMetadata, ToolKind
from ant_orchestrator.application.ports.tool_errors import ToolAdapterError, ToolNotFoundError
from ant_orchestrator.core.domain.errors import InvariantViolation
from tests.contracts.git_read_contract import GitReadContract
from tests.support.fake_git_read import FakeGitReadAdapter

_WRITE_OPERATIONS = {
    "add",
    "commit",
    "push",
    "pull",
    "fetch",
    "merge",
    "rebase",
    "reset",
    "checkout",
    "switch",
    "branch",
    "tag",
    "stash",
    "clean",
    "restore",
    "apply",
}


def _meta(operation: str) -> ToolInvocationMetadata:
    return ToolInvocationMetadata(tool=ToolKind.GIT, operation=operation)


def _dirty_status() -> GitStatusResult:
    return GitStatusResult(
        entries=(GitChange(path="a.py", change_kind=ChangeKind.MODIFIED),),
        is_clean=False,
        invocation=_meta("status"),
    )


def _non_empty_diff() -> GitDiffResult:
    return GitDiffResult(
        changes=(GitChange(path="a.py", change_kind=ChangeKind.MODIFIED),),
        diff_text="--- a/a.py\n+++ b/a.py\n",
        invocation=_meta("diff"),
    )


class TestFakeGitReadContract(GitReadContract):
    def build_clean_adapter(self) -> GitReadAdapter:
        return FakeGitReadAdapter()

    def build_dirty_adapter(self) -> GitReadAdapter:
        return FakeGitReadAdapter(status_result=_dirty_status(), diff_result=_non_empty_diff())

    def build_error_adapter(self, error: ToolAdapterError) -> GitReadAdapter:
        return FakeGitReadAdapter(error=error)


def test_protocol_exposes_no_write_operations() -> None:
    members = {name for name in vars(GitReadAdapter) if not name.startswith("_")}
    assert "status" in members and "diff" in members
    assert not (members & _WRITE_OPERATIONS)


def test_fake_records_requests() -> None:
    adapter = FakeGitReadAdapter()
    request = GitStatusRequest()
    asyncio.run(adapter.status(request))
    assert adapter.status_requests == [request]


def test_repository_not_found_simulation() -> None:
    adapter = FakeGitReadAdapter(error=ToolNotFoundError(tool="git"))
    with pytest.raises(ToolNotFoundError):
        asyncio.run(adapter.status(GitStatusRequest()))


def test_clean_status_cannot_have_entries() -> None:
    with pytest.raises(InvariantViolation):
        GitStatusResult(
            entries=(GitChange(path="a", change_kind=ChangeKind.MODIFIED),),
            is_clean=True,
            invocation=_meta("status"),
        )


def test_git_change_rejects_empty_path() -> None:
    with pytest.raises(InvariantViolation):
        GitChange(path="", change_kind=ChangeKind.MODIFIED)
