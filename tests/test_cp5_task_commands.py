"""CP5 — task show and task result command tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from ant_orchestrator.application.models.execution_views import (
    ApprovalView,
    EnergyTotalsView,
    TaskDetailView,
    WorkflowRunSummaryView,
)
from ant_orchestrator.application.models.result_views import (
    ArtifactRefView,
    FailureInfoView,
    TaskResultView,
)
from ant_orchestrator.application.ports.database import RecordNotFound
from ant_orchestrator.cli.main import app

runner = CliRunner()

_TASK_ID = "task-abc-123"


def _make_detail(
    status: str = "created",
    active_run: WorkflowRunSummaryView | None = None,
    approvals: tuple[ApprovalView, ...] = (),
) -> TaskDetailView:
    return TaskDetailView(
        task_id=_TASK_ID,
        title="Test task",
        status=status,
        priority="normal",
        source="local_cli",
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:01:00+00:00",
        active_workflow_run=active_run,
        worker_runs=(),
        energy_totals=EnergyTotalsView(tokens_in=10, tokens_out=5, record_count=1),
        approvals=approvals,
    )


def _make_run(status: str = "running") -> WorkflowRunSummaryView:
    return WorkflowRunSummaryView(
        workflow_run_id="run-xyz",
        status=status,
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:00:30+00:00",
        cancel_requested=False,
    )


def _make_result(
    outcome: str = "completed",
    failure: FailureInfoView | None = None,
    artifacts: tuple[ArtifactRefView, ...] = (),
) -> TaskResultView:
    return TaskResultView(
        result_id="result-001",
        task_id=_TASK_ID,
        workflow_run_id="run-xyz",
        outcome=outcome,
        summary="All done",
        artifact_refs=artifacts,
        failure=failure,
        finalized_at="2025-01-01T01:00:00+00:00",
        result_version=1,
    )


def _make_artifact() -> ArtifactRefView:
    return ArtifactRefView(
        artifact_id="art-001",
        kind="output",
        relative_path="artifacts/output.txt",
        media_type="text/plain",
        sha256="a" * 64,
        size_bytes=1234,
        created_by_attempt_id=None,
        state="committed",
        metadata="{}",
    )


class TestTaskShow:
    def _patch_show(self, monkeypatch: pytest.MonkeyPatch, detail: TaskDetailView) -> None:
        mock_svc = MagicMock()
        mock_svc.get_task_detail.get.return_value = detail
        monkeypatch.setattr(
            "ant_orchestrator.cli.cp5_task_detail.build_workflow_services",
            lambda _: mock_svc,
        )

    def test_existing_task_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_show(monkeypatch, _make_detail())
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path)])
        assert result.exit_code == 0

    def test_shows_task_id(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_show(monkeypatch, _make_detail())
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path)])
        assert _TASK_ID in result.output

    def test_shows_status(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_show(monkeypatch, _make_detail(status="running"))
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path)])
        assert "running" in result.output

    def test_shows_workflow_run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_show(monkeypatch, _make_detail(active_run=_make_run()))
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path)])
        assert "run-xyz" in result.output

    def test_unknown_task_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_svc = MagicMock()
        mock_svc.get_task_detail.get.side_effect = RecordNotFound("not found")
        monkeypatch.setattr(
            "ant_orchestrator.cli.cp5_task_detail.build_workflow_services",
            lambda _: mock_svc,
        )
        result = runner.invoke(app, ["task", "show", "no-such-task", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_json_valid(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_show(monkeypatch, _make_detail())
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["task_id"] == _TASK_ID
        assert "status" in data

    def test_json_no_raw_provider_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        detail = _make_detail()
        self._patch_show(monkeypatch, detail)
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        # No traceback or raw keys
        assert "traceback" not in str(data)
        assert "raw" not in str(data).lower()

    def test_waiting_approval_shown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        approval = ApprovalView(
            approval_id="appr-001",
            status="pending",
            gate_type="human",
            requested_at="2025-01-01T00:00:00+00:00",
            decided_at=None,
            reason=None,
        )
        self._patch_show(
            monkeypatch, _make_detail(status="awaiting_approval", approvals=(approval,))
        )
        result = runner.invoke(app, ["task", "show", _TASK_ID, "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert data["approval_count"] == 1


class TestTaskResult:
    def _patch_result(
        self, monkeypatch: pytest.MonkeyPatch, result_view: TaskResultView | None
    ) -> None:
        mock_svc = MagicMock()
        mock_svc.get_task_result.get.return_value = result_view
        monkeypatch.setattr(
            "ant_orchestrator.cli.cp5_task_detail.build_workflow_services",
            lambda _: mock_svc,
        )

    def test_completed_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, _make_result())
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path)])
        assert result.exit_code == 0

    def test_not_ready_exits_0(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, None)
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path)])
        assert result.exit_code == 0

    def test_not_ready_shows_message(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, None)
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path)])
        out = result.output.lower()
        assert "not yet available" in out or "not ready" in out or _TASK_ID in result.output

    def test_unknown_task_nonzero(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_svc = MagicMock()
        mock_svc.get_task_result.get.side_effect = RecordNotFound("task not found")
        monkeypatch.setattr(
            "ant_orchestrator.cli.cp5_task_detail.build_workflow_services",
            lambda _: mock_svc,
        )
        result = runner.invoke(app, ["task", "result", "no-such-task", "--path", str(tmp_path)])
        assert result.exit_code != 0

    def test_json_completed(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, _make_result())
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert data["task_id"] == _TASK_ID
        assert data["outcome"] == "completed"

    def test_json_not_ready(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, None)
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert data["ready"] is False

    def test_failed_outcome_retrievable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        failure = FailureInfoView(code="E001", message="oops", retryable=False, source="worker")
        self._patch_result(monkeypatch, _make_result(outcome="failed", failure=failure))
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["outcome"] == "failed"
        assert data["failure"]["code"] == "E001"

    def test_artifact_refs_shown(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        art = _make_artifact()
        self._patch_result(monkeypatch, _make_result(artifacts=(art,)))
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        data = json.loads(result.output)
        assert len(data["artifact_refs"]) == 1
        assert data["artifact_refs"][0]["relative_path"] == "artifacts/output.txt"

    def test_artifact_no_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        art = _make_artifact()
        self._patch_result(monkeypatch, _make_result(artifacts=(art,)))
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        # relative_path must not be an absolute path
        data = json.loads(result.output)
        rel = data["artifact_refs"][0]["relative_path"]
        from pathlib import PurePath

        assert not PurePath(rel).is_absolute()

    def test_rejected_outcome_retrievable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_result(monkeypatch, _make_result(outcome="rejected"))
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["outcome"] == "rejected"

    def test_cancelled_outcome_retrievable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_result(monkeypatch, _make_result(outcome="cancelled"))
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        assert result.exit_code == 0

    def test_sanitized_no_traceback(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self._patch_result(monkeypatch, _make_result())
        result = runner.invoke(app, ["task", "result", _TASK_ID, "--path", str(tmp_path), "--json"])
        assert "Traceback" not in result.output
        assert "traceback" not in result.output
