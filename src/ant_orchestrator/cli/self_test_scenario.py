"""Deterministic end-to-end workflow scenario for the self-test (Phase 8 CP6).

Drives one task from creation to a terminal TaskResult through the real Phase-4
application services wired with a deterministic stub worker, then verifies the
durable evidence (single run, finalized result, idempotency). This is explicitly a
verification scenario — never presented as an AI-generated production task.
"""

from __future__ import annotations

from ant_orchestrator.application.errors import WorkflowStateError
from ant_orchestrator.cli.composition_self_test import SelfTestComposition
from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    CheckResult,
)
from ant_orchestrator.config.constants import TASK_RESULT_VERSION
from ant_orchestrator.core.domain.enums import TaskPriority
from ant_orchestrator.workers.stub import DeterministicStubAdapter

_SELF_TEST_TITLE = "Self-test: verify deterministic workflow plumbing"


def workflow_and_result_checks(composition: SelfTestComposition) -> list[CheckResult]:
    """Run the deterministic scenario and return workflow + result checks."""
    services = composition.services
    results: list[CheckResult] = []

    task = services.create_task.create(title=_SELF_TEST_TITLE, priority=TaskPriority.NORMAL)
    task_id = task.id.value
    results.append(
        CheckResult(
            "workflow.task_create",
            STATUS_PASS if task.status.value == "created" else STATUS_FAIL,
            f"task created ({task.status.value})",
        )
    )

    outcome = services.run_workflow.execute(task_id)
    run_id = outcome.run_id
    results.append(
        CheckResult(
            "workflow.start",
            STATUS_PASS if run_id else STATUS_FAIL,
            "exactly one workflow run started" if run_id else "no workflow run id",
        )
    )
    results.append(
        CheckResult(
            "workflow.worker_execute",
            STATUS_PASS if outcome.status == "completed" else STATUS_FAIL,
            "deterministic worker executed (SUCCESS)",
        )
    )
    results.append(
        CheckResult(
            "workflow.complete",
            STATUS_PASS if outcome.status == "completed" else STATUS_FAIL,
            f"terminal status: {outcome.status}",
        )
    )
    results.append(_no_duplicate_run_check(composition, task_id))
    results.extend(_result_checks(composition, task_id, run_id))
    return results


def _no_duplicate_run_check(composition: SelfTestComposition, task_id: str) -> CheckResult:
    """Re-running a terminal task must not create a second run (idempotency)."""
    try:
        composition.services.run_workflow.execute(task_id)
        reran = True
    except WorkflowStateError:
        reran = False
    runs = _count(composition, "workflow_runs", task_id)
    ok = runs == 1 and not reran
    return CheckResult(
        "workflow.no_duplicate_run",
        STATUS_PASS if ok else STATUS_FAIL,
        f"{runs} run row(s); terminal re-run rejected" if ok else f"{runs} run row(s)",
    )


def _result_checks(
    composition: SelfTestComposition, task_id: str, run_id: str | None
) -> list[CheckResult]:
    services = composition.services
    view = services.get_task_result.get(task_id)
    if view is None:
        return [
            CheckResult("result.finalized", STATUS_FAIL, "no TaskResult was persisted"),
            CheckResult("result.retrieve", STATUS_SKIP, "no result to retrieve"),
            CheckResult("result.artifact_digest", STATUS_SKIP, "no result"),
            CheckResult("result.no_duplicate", STATUS_SKIP, "no result"),
        ]
    results = [
        CheckResult(
            "result.finalized",
            STATUS_PASS if view.outcome == "completed" else STATUS_FAIL,
            f"result outcome: {view.outcome}",
        ),
        CheckResult(
            "result.retrieve",
            STATUS_PASS if view.result_version == TASK_RESULT_VERSION else STATUS_FAIL,
            f"retrieved result v{view.result_version}",
        ),
    ]
    results.append(_artifact_digest_check(view))
    count = _count(composition, "task_results", task_id)
    results.append(
        CheckResult(
            "result.no_duplicate",
            STATUS_PASS if count == 1 else STATUS_FAIL,
            f"{count} result row(s) for task",
        )
    )
    return results


def _artifact_digest_check(view: object) -> CheckResult:
    """Verify each artifact ref has a valid digest/size, or SKIP when none exist."""
    refs = getattr(view, "artifact_refs", ())
    if not refs:
        return CheckResult(
            "result.artifact_digest",
            STATUS_SKIP,
            "deterministic stub produces no artifacts",
        )
    for ref in refs:
        sha = getattr(ref, "sha256", "")
        size = getattr(ref, "size_bytes", -1)
        if len(sha) != 64 or size < 0 or ref.relative_path.startswith(("/", "\\")):
            return CheckResult(
                "result.artifact_digest", STATUS_FAIL, "invalid artifact digest/path"
            )
    return CheckResult("result.artifact_digest", STATUS_PASS, f"{len(refs)} artifact ref(s) valid")


def stub_isolation_check(composition: SelfTestComposition) -> CheckResult:
    """Confirm the self-test composition uses the deterministic stub worker."""
    is_stub = isinstance(composition.worker, DeterministicStubAdapter)
    return CheckResult(
        "security.stub_isolated",
        STATUS_PASS if is_stub else STATUS_FAIL,
        "self-test worker is the deterministic stub",
    )


def _count(composition: SelfTestComposition, table: str, task_id: str) -> int:
    with composition.database.connect() as conn:
        row = conn.execute(f"SELECT count(*) FROM {table} WHERE task_id = ?", (task_id,)).fetchone()
    return int(row[0]) if row else 0
