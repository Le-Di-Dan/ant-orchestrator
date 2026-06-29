"""CP6 — isolated deterministic self-test command, lifecycle, security & output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from ant_orchestrator.cli.composition_self_test import (
    DeterministicClock,
    SequentialIdGenerator,
    build_self_test_services,
)
from ant_orchestrator.cli.main import app
from ant_orchestrator.cli.self_test_runner import SelfTestRunner
from ant_orchestrator.cli.self_test_view import (
    SELF_TEST_JSON_SCHEMA_VERSION,
    render_json,
)
from ant_orchestrator.config.constants import ANT_CLI_VERSION
from ant_orchestrator.workers.stub import DeterministicStubAdapter

runner = CliRunner()

_REQUIRED_CHECK_IDS = {
    "runtime.version",
    "workspace.create",
    "workspace.marker",
    "database.schema_v5",
    "checkpoint.write_read",
    "audit.redaction",
    "workflow.complete",
    "workflow.no_duplicate_run",
    "result.finalized",
    "result.retrieve",
    "result.artifact_digest",
    "security.no_network",
    "security.workspace_boundary",
    "security.stub_isolated",
    "cleanup.workspace",
}


def _report():
    return SelfTestRunner().run()


# --- deterministic clock / ids ------------------------------------------------


def test_deterministic_clock_is_monotonic() -> None:
    clock = DeterministicClock()
    first = clock.now()
    second = clock.now()
    assert second.value > first.value


def test_sequential_ids_are_unique_and_stable() -> None:
    gen = SequentialIdGenerator()
    assert gen.new_id() == "selftest-0000"
    assert gen.new_id() == "selftest-0001"


# --- end-to-end report --------------------------------------------------------


def test_self_test_overall_pass_and_all_required_checks() -> None:
    report = _report()
    ids = {c.check_id for c in report.checks}
    assert _REQUIRED_CHECK_IDS <= ids
    assert report.overall == "PASS"
    assert not report.has_failure
    assert report.duration_ms >= 0
    assert report.workspace_cleaned is True


def test_workflow_scenario_is_deterministic_completed() -> None:
    report = _report()
    by_id = {c.check_id: c for c in report.checks}
    assert by_id["workflow.complete"].status == "PASS"
    assert by_id["workflow.no_duplicate_run"].status == "PASS"
    assert by_id["result.finalized"].status == "PASS"
    assert by_id["result.no_duplicate"].status == "PASS"


def test_artifact_digest_verifies_real_pipeline() -> None:
    """CP7 carry-forward B: the self-test must verify a real artifact, never SKIP."""
    by_id = {c.check_id: c for c in _report().checks}
    assert by_id["result.artifact_digest"].status == "PASS"


def test_self_test_artifact_persisted_and_idempotent(tmp_path: Path) -> None:
    """The deterministic internal artifact is written, persisted with a valid digest,
    retrievable, and a terminal re-run never duplicates it."""
    import hashlib

    from ant_orchestrator.cli.composition import build_services
    from ant_orchestrator.cli.self_test_artifact import (
        SELF_TEST_ARTIFACT_CONTENT,
        SELF_TEST_ARTIFACT_RELATIVE_PATH,
    )
    from ant_orchestrator.cli.self_test_scenario import workflow_and_result_checks

    build_services().init_nest.init(tmp_path)
    composition = build_self_test_services(tmp_path)
    workflow_and_result_checks(composition)

    on_disk = (composition.artifacts_root / SELF_TEST_ARTIFACT_RELATIVE_PATH).read_bytes()
    expected = SELF_TEST_ARTIFACT_CONTENT.encode("utf-8")
    assert on_disk == expected

    # A second scenario pass (terminal re-run rejected) must not duplicate the result/ref.
    with composition.database.connect() as conn:
        results = conn.execute("SELECT COUNT(*) FROM task_results").fetchone()[0]
        artifacts = conn.execute("SELECT sha256, size_bytes FROM task_result_artifacts").fetchall()
    assert results == 1
    assert len(artifacts) == 1
    assert artifacts[0][0] == hashlib.sha256(expected).hexdigest()
    assert artifacts[0][1] == len(expected)


# --- composition isolation ----------------------------------------------------


def test_self_test_composition_uses_stub(tmp_path: Path) -> None:
    from ant_orchestrator.cli.composition import build_services

    build_services().init_nest.init(tmp_path)
    composition = build_self_test_services(tmp_path)
    assert isinstance(composition.worker, DeterministicStubAdapter)


# --- workspace lifecycle ------------------------------------------------------


def test_cleanup_removes_temporary_workspace() -> None:
    report = _report()
    assert report.workspace_cleaned is True
    assert report.kept_workspace_path is None


def test_keep_workspace_reports_path_and_skips_cleanup() -> None:
    report = SelfTestRunner(keep_workspace=True).run()
    assert report.kept_workspace_path is not None
    kept = Path(report.kept_workspace_path)
    try:
        assert kept.exists()
        assert report.workspace_cleaned is False
        by_id = {c.check_id: c for c in report.checks}
        assert by_id["cleanup.workspace"].status == "SKIP"
    finally:
        import shutil

        shutil.rmtree(kept, ignore_errors=True)


def test_self_test_does_not_mutate_current_project(tmp_path: Path) -> None:
    from ant_orchestrator.cli.composition import build_services

    build_services().init_nest.init(tmp_path)
    before = sorted(p.name for p in (tmp_path / ".ant").rglob("*"))
    SelfTestRunner().run()
    after = sorted(p.name for p in (tmp_path / ".ant").rglob("*"))
    assert before == after


# --- command (CliRunner) ------------------------------------------------------


def test_command_human_output_exit_zero() -> None:
    result = runner.invoke(app, ["self-test"])
    assert result.exit_code == 0
    assert "Overall: PASS" in result.stdout
    assert f"Self-Test {ANT_CLI_VERSION}" in result.stdout


def test_command_json_output_schema() -> None:
    result = runner.invoke(app, ["self-test", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == SELF_TEST_JSON_SCHEMA_VERSION
    assert payload["command"] == "self-test"
    assert payload["version"] == ANT_CLI_VERSION
    assert payload["overall_status"] == "PASS"
    assert payload["workspace_cleaned"] is True
    assert payload["duration_ms"] >= 0
    assert isinstance(payload["checks"], list) and payload["checks"]
    # No ANSI escape sequences in JSON output.
    assert "\x1b[" not in result.stdout


# --- security -----------------------------------------------------------------


def test_no_network_check_passes() -> None:
    by_id = {c.check_id: c for c in _report().checks}
    assert by_id["security.no_network"].status == "PASS"


def test_real_api_key_value_never_leaks(monkeypatch: pytest.MonkeyPatch) -> None:
    canary = "sk-leakcanaryAAAAAAAAAAAAAAAAAAAA"
    monkeypatch.setenv("OPENAI_API_KEY", canary)
    result = runner.invoke(app, ["self-test", "--json"])
    assert result.exit_code == 0
    assert canary not in result.stdout
    payload = json.loads(result.stdout)
    by_id = {c["check_id"]: c for c in payload["checks"]}
    assert by_id["security.no_secret"]["status"] == "PASS"


def test_human_output_has_no_absolute_path_by_default() -> None:
    result = runner.invoke(app, ["self-test"])
    assert "ant-selftest-" not in result.stdout


def test_json_payload_has_stable_check_ids() -> None:
    payload = render_json(_report())
    ids = {c["check_id"] for c in payload["checks"]}
    assert _REQUIRED_CHECK_IDS <= ids
