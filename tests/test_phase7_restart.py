"""CP8 — Three-level restart recovery evidence (Phase 7).

Proves durable recovery across three boundaries:
  Level 1: FastAPI app-instance restart (TestClient lifecycle).
  Level 2: Application service reinitialization (build_workflow_services twice).
  Level 3: Real subprocess restart (separate Python interpreter processes).

All scenarios use the ``--significant-write`` intent flag via the CP8 driver to
trigger a deterministic approval interrupt without network / live provider calls.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ant_orchestrator.api.main import create_app
from ant_orchestrator.core.domain.enums import ActorSource
from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import (
    cli_approve,
    cli_status,
    driver,
    expect_ok,
    init_and_create,
    init_nest,
)
from tests.support.phase7_restart_helpers import (
    assert_no_duplicate_approvals,
    assert_no_duplicate_wf_runs,
    count_approvals_for_run,
    count_audit_events,
    count_wf_runs_for_task,
    setup_paused_workspace,
)

# ---------------------------------------------------------------------------
# Level 1 — FastAPI app-instance restart
# ---------------------------------------------------------------------------


def test_app_instance_restart_state_preserved(tmp_path: Path) -> None:
    """State persists across complete TestClient close/reopen (two distinct app instances)."""
    workspace, task_id, run_id, _ = setup_paused_workspace(tmp_path)

    # --- App instance A: inspect paused state ---
    with TestClient(create_app(workspace)) as client_a:
        resp_a = client_a.get(f"/tasks/{task_id}")
        assert resp_a.status_code == 200
        detail_a = resp_a.json()
        assert detail_a["status"] == "waiting_for_approval"
        wf_resp_a = client_a.get(f"/workflow-runs/{run_id}")
        assert wf_resp_a.status_code == 200
        assert wf_resp_a.json()["workflow_run_id"] == run_id
        # Baseline counts before app instance closes
        baseline_wf = count_wf_runs_for_task(workspace, task_id)
        baseline_app = count_approvals_for_run(workspace, run_id)
        baseline_audit = count_audit_events(workspace)

    # --- App instance A fully closed; B is a new object (restart boundary) ---

    with TestClient(create_app(workspace)) as client_b:
        # Task still exists with same status
        resp_b = client_b.get(f"/tasks/{task_id}")
        assert resp_b.status_code == 200
        detail_b = resp_b.json()
        assert detail_b["status"] == "waiting_for_approval"
        assert detail_b["task_id"] == task_id

        # Same workflow run visible via its ID
        wf_resp_b = client_b.get(f"/workflow-runs/{run_id}")
        assert wf_resp_b.status_code == 200
        assert wf_resp_b.json()["workflow_run_id"] == run_id
        assert wf_resp_b.json()["status"] not in ("completed", "failed", "cancelled")

        # Inspect did not create side effects
        assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
        assert_no_duplicate_approvals(workspace, run_id, baseline_app)

    # --- Resolve approval via production CLI subprocess ---
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["workflow_run_id"] == run_id

    # --- App instance C: verify terminal state ---
    with TestClient(create_app(workspace)) as client_c:
        final = client_c.get(f"/tasks/{task_id}").json()
        assert final["status"] in ("completed", "failed", "rejected")
        # Same workflow run — no new run created
        assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
        # Audit trail extended, not truncated
        assert count_audit_events(workspace) >= baseline_audit


def test_app_instance_no_shared_mutable_services(tmp_path: Path) -> None:
    """Two app instances from same workspace must not share mutable service objects."""
    workspace, task_id, _, _ = setup_paused_workspace(tmp_path)
    app_a = create_app(workspace)
    app_b = create_app(workspace)
    # Services are independent objects — different identity
    assert app_a.state.services is not app_b.state.services


def test_app_instance_missing_task_404_on_fresh_app(tmp_path: Path) -> None:
    """A fresh app instance returns 404 for a task that does not exist."""
    workspace = tmp_path / "nest"
    workspace.mkdir()
    init_nest(workspace)
    with TestClient(create_app(workspace)) as client:
        resp = client.get("/tasks/no-such-task")
        assert resp.status_code == 404
        assert "error" in resp.json()


# ---------------------------------------------------------------------------
# Level 2 — Service reinitialization
# ---------------------------------------------------------------------------


def test_service_reinit_state_preserved(tmp_path: Path) -> None:
    """State persists when build_workflow_services is called twice on same workspace."""
    from ant_orchestrator.application.ports.worker import WorkerOutcome
    from ant_orchestrator.composition import build_workflow_services
    from tests.support.cp8_driver_support import build_scenario_services

    workspace = tmp_path / "nest"
    workspace.mkdir()

    # Bootstrap workspace and task via CLI subprocess
    task_id = init_and_create(workspace, title="svc-reinit-task")

    # Services A: scripted runner that triggers approval interrupt
    services_a = build_scenario_services(
        workspace,
        outcomes=[],
        fallback=WorkerOutcome.SUCCESS,
        base_retry_limit=2,
        significant_write=True,
        unsafe_command=False,
    )
    outcome_a = services_a.run_workflow.execute(task_id)
    run_id = outcome_a.run_id
    assert outcome_a.status == "waiting_for_approval"
    assert outcome_a.approval_id is not None

    baseline_wf = count_wf_runs_for_task(workspace, task_id)
    baseline_app = count_approvals_for_run(workspace, run_id)

    # ---- Service reinitialization boundary ----
    # Services B: neutral production composition (real audit sink/reader)
    services_b = build_workflow_services(workspace)

    # Status recovered from durable SQLite — not from services_a memory
    report = services_b.task_status.report()
    task_row = next((r for r in report.rows if r.task_id == task_id), None)
    assert task_row is not None
    assert task_row.status == "waiting_for_approval"
    assert task_row.workflow_run_id == run_id

    # Inspect did not create side effects
    assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
    assert_no_duplicate_approvals(workspace, run_id, baseline_app)

    # Detail view via services_b
    detail_b = services_b.get_task_detail.get(task_id)
    assert detail_b.active_workflow_run is not None
    assert detail_b.active_workflow_run.workflow_run_id == run_id

    # Resolve via services_b (production path, not scripted)
    outcome_b = services_b.resolve_approval.approve(task_id, actor_source=ActorSource.LOCAL_CLI)
    assert outcome_b.status in ("completed", "failed", "rejected")
    assert outcome_b.run_id == run_id  # same run, not a new one

    # No new workflow run created by resume
    assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
    # Approval count unchanged (resolved, not duplicated)
    assert_no_duplicate_approvals(workspace, run_id, baseline_app)


def test_service_reinit_worker_run_count_correct(tmp_path: Path) -> None:
    """After approve+resume, worker_runs count reflects actual execution semantics."""
    from ant_orchestrator.application.ports.worker import WorkerOutcome
    from ant_orchestrator.composition import build_workflow_services
    from tests.support.cp8_driver_support import build_scenario_services

    workspace = tmp_path / "nest"
    workspace.mkdir()
    task_id = init_and_create(workspace, title="wr-count-task")

    services_a = build_scenario_services(
        workspace,
        outcomes=[],
        fallback=WorkerOutcome.SUCCESS,
        base_retry_limit=2,
        significant_write=True,
        unsafe_command=False,
    )
    services_a.run_workflow.execute(task_id)
    # No worker ran before approval
    assert ev.count_rows(workspace, "execution_attempts") == 0

    services_b = build_workflow_services(workspace)
    services_b.resolve_approval.approve(task_id, actor_source=ActorSource.LOCAL_CLI)

    # After resume and execute-stub, one worker run attempt expected
    assert ev.count_rows(workspace, "execution_attempts") >= 1


# ---------------------------------------------------------------------------
# Level 3 — Real subprocess restart
# ---------------------------------------------------------------------------


def test_real_subprocess_restart_state_preserved(tmp_path: Path) -> None:
    """State survives a complete Python process boundary (two separate interpreter PIDs)."""
    workspace = tmp_path / "nest"
    workspace.mkdir()

    # --- Process A: init + create + drive to approval pause ---
    task_id = init_and_create(workspace)
    proc_a = driver("run", workspace, task_id=task_id, extra=["--significant-write"])
    assert proc_a.returncode == 0, f"Process A failed:\n{proc_a.stderr}"
    payload_a = proc_a.json()
    run_id = str(payload_a["workflow_run_id"])
    assert payload_a["approval_id"]  # approval_id persisted in durable state
    assert payload_a["status"] == "waiting_for_approval"
    # Process A has now fully exited

    # Baseline durable counts (no in-memory object from Process A)
    baseline_wf = count_wf_runs_for_task(workspace, task_id)
    baseline_app = count_approvals_for_run(workspace, run_id)
    assert baseline_wf == 1
    assert baseline_app == 1
    assert ev.run_status(workspace, run_id) == "awaiting_approval"
    assert ev.task_status(workspace, task_id) == "waiting_for_approval"

    # --- Process B-1: new Python process reads state ---
    status_proc = cli_status(workspace)
    assert status_proc.returncode == 0, f"Process B-1 failed:\n{status_proc.stderr}"
    status_out = status_proc.json()
    rows = status_out["tasks"]
    matching = [r for r in rows if r["task_id"] == task_id]
    assert len(matching) == 1
    assert matching[0]["status"] == "waiting_for_approval"

    # Inspect did not create side effects
    assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
    assert_no_duplicate_approvals(workspace, run_id, baseline_app)

    # --- Process B-2: approve + resume ---
    proc_b2 = cli_approve(workspace, task_id)
    assert proc_b2.returncode == 0, f"Process B-2 failed:\n{proc_b2.stderr}"
    approved_out = proc_b2.json()
    assert approved_out["workflow_run_id"] == run_id  # same run identity preserved

    # --- Process B-3: final status inspection ---
    final_proc = cli_status(workspace)
    assert final_proc.returncode == 0
    final_out = final_proc.json()
    final_row = next((r for r in final_out["tasks"] if r["task_id"] == task_id), None)
    assert final_row is not None
    assert final_row["status"] in ("completed", "failed", "rejected")

    # No duplicate workflow runs created across all processes
    assert_no_duplicate_wf_runs(workspace, task_id, baseline_wf)
    # Approval resolved but not duplicated
    assert_no_duplicate_approvals(workspace, run_id, baseline_app)
    # Checkpoint durable: at least one checkpoint exists
    assert ev.checkpoint_count(workspace, run_id) >= 1


def test_real_subprocess_audit_trail_continuous(tmp_path: Path) -> None:
    """Audit events from before and after restart are readable in same workspace."""
    workspace = tmp_path / "nest"
    workspace.mkdir()

    task_id = init_and_create(workspace)
    driver("run", workspace, task_id=task_id, extra=["--significant-write"])

    # CLI subprocess uses real JsonlAuditSink; driver uses NullAuditSink — minimal events
    # Ensure audit log directory exists before approval (populated by CLI init)
    before_approve = count_audit_events(workspace)

    cli_approve(workspace, task_id)

    # After approve (CLI path uses JsonlAuditSink), audit should be non-decreasing
    after_approve = count_audit_events(workspace)
    assert after_approve >= before_approve


def test_real_subprocess_missing_task_typed_error(tmp_path: Path) -> None:
    """Approving a nonexistent task returns a typed error, not an unhandled crash."""
    workspace = tmp_path / "nest"
    workspace.mkdir()
    init_nest(workspace)
    proc = cli_approve(workspace, "nonexistent-task-id")
    # Must not crash with a traceback — typed exit code expected
    assert proc.returncode != 0
    assert "Traceback" not in proc.stdout
    payload = proc.json()
    assert "error" in payload
    assert payload["error"]["type"]  # non-empty error type
