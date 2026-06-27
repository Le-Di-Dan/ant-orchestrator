"""CP8 — Scenarios D/E: finite retry + RetryGrant, regroup + scope-change (subprocess).

These branches are unreachable from the vanilla production stub (always SUCCESS), so
process A uses the test-only scripted-stub driver to emit RETRYABLE_FAILURE /
REVIEW_REGROUP sequences. Resolution still happens in a fresh process (public CLI
when the stub-default SUCCESS continuation is enough; the scripted driver when the
post-resume branch must itself fail). All evidence is read back from disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.support import cp8_evidence as ev
from tests.support.cp8_harness import cli_approve, cli_reject, driver, expect_ok, init_and_create


def _nest(tmp_path: Path) -> Path:
    workspace = tmp_path / "nest"
    workspace.mkdir()
    return workspace


def _sanitized(workspace: Path) -> dict[str, object]:
    payload = json.loads(ev.approvals(workspace)[0]["request_json"])
    inner = payload.get("sanitized_payload")
    return inner if isinstance(inner, dict) else {}


# ---------------------------------------------------------------------------
# Scenario D — finite retry (base=2 → 3 attempts) then RetryGrant
# ---------------------------------------------------------------------------


def test_scenario_d_three_attempts_then_retry_limit_gate(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    paused = expect_ok(
        "driver run",
        driver(
            "run",
            workspace,
            task_id=task_id,
            extra=["--outcomes", "retryable_failure,retryable_failure,retryable_failure"],
        ),
    )
    run_id = str(paused["workflow_run_id"])
    assert paused["status"] == "waiting_for_approval"

    # Exactly 3 distinct failed attempts; only the 3rd failure escalates.
    attempts = ev.execution_attempts(workspace)
    assert [r["attempt_no"] for r in attempts] == [1, 2, 3]
    assert all(r["status"] == "failed" for r in attempts)

    approval = ev.approvals(workspace)[0]
    assert approval["gate_type"] == "retry_limit"
    sanitized = _sanitized(workspace)
    assert sanitized.get("retry_count") == 2  # retry_count == eff_limit, not stored separately
    assert sanitized.get("effective_retry_limit") == 2

    # --- Process B: public CLI approve → RetryGrant → 4th attempt succeeds ---
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"

    attempts_after = ev.execution_attempts(workspace)
    assert [r["attempt_no"] for r in attempts_after] == [1, 2, 3, 4]
    assert attempts_after[3]["status"] == "succeeded"
    # The earlier terminal attempts are not overwritten.
    assert [r["status"] for r in attempts_after[:3]] == ["failed", "failed", "failed"]
    # Exactly one extension granted; computed effective limit (not an independent store).
    assert ev.latest_state_values(workspace, run_id).get("retry_extension_count") == 1
    assert ev.succeeded_attempt_count(workspace) == 1

    # Duplicate approve after completion is idempotent (no fifth attempt, no new grant).
    again = cli_approve(workspace, task_id)
    assert again.returncode == 0
    assert ev.count_rows(workspace, "execution_attempts") == 4


def test_scenario_d_retry_grant_bound_fails_closed(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    expect_ok(
        "driver run",
        driver(
            "run",
            workspace,
            task_id=task_id,
            extra=["--outcomes", "retryable_failure,retryable_failure,retryable_failure"],
        ),
    )
    # Process B (scripted): grant one retry, but the granted attempts fail again →
    # a second RETRY_LIMIT gate (extension now at the MAX_RETRY_EXTENSIONS bound).
    second = expect_ok(
        "driver approve",
        driver(
            "approve",
            workspace,
            task_id=task_id,
            extra=["--outcomes", "retryable_failure,retryable_failure"],
        ),
    )
    assert second["status"] == "waiting_for_approval"
    assert ev.count_rows(workspace, "execution_attempts") == 5

    # Process C: public CLI approve at the bound → fail closed (FAILED, no new attempt).
    failed = expect_ok("approve", cli_approve(workspace, task_id))
    assert failed["status"] == "failed"
    assert ev.task_status(workspace, task_id) == "failed"
    assert ev.count_rows(workspace, "execution_attempts") == 5


# ---------------------------------------------------------------------------
# Scenario E — regroup once, then SCOPE_CHANGE escalation + REPLAN continuation
# ---------------------------------------------------------------------------


def test_scenario_e_regroup_then_scope_change_approve_replans(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    paused = expect_ok(
        "driver run",
        driver(
            "run",
            workspace,
            task_id=task_id,
            extra=["--outcomes", "review_regroup,review_regroup"],
        ),
    )
    run_id = str(paused["workflow_run_id"])
    assert paused["status"] == "waiting_for_approval"

    approval = ev.approvals(workspace)[0]
    assert approval["gate_type"] == "scope_change"
    assert _sanitized(workspace).get("regroup_count") == 1

    state = ev.latest_state_values(workspace, run_id)
    assert state.get("regroup_count") == 1
    plan = state.get("plan")
    assert isinstance(plan, dict) and plan.get("plan_revision") == 1
    counts_before = ev.node_schedule_counts(workspace, run_id)
    assert counts_before.get("plan") == 2  # initial plan + one automatic regroup replan

    # --- Process B: public CLI approve SCOPE_CHANGE → REPLAN continuation → completes ---
    approved = expect_ok("approve", cli_approve(workspace, task_id))
    assert approved["status"] == "completed"
    counts_after = ev.node_schedule_counts(workspace, run_id)
    assert counts_after["plan"] == counts_before["plan"] + 1  # only the approved REPLAN
    assert ev.task_status(workspace, task_id) == "completed"


def test_scenario_e_reject_scope_change_terminal(tmp_path: Path) -> None:
    workspace = _nest(tmp_path)
    task_id = init_and_create(workspace)

    expect_ok(
        "driver run",
        driver(
            "run",
            workspace,
            task_id=task_id,
            extra=["--outcomes", "review_regroup,review_regroup"],
        ),
    )
    rejected = expect_ok("reject", cli_reject(workspace, task_id, reason="scope too large"))
    assert rejected["status"] == "rejected"
    assert ev.task_status(workspace, task_id) == "rejected"
    assert ev.approvals(workspace)[0]["status"] == "rejected"
