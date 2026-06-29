"""Deterministic end-to-end workflow scenario for the self-test (Phase 8 CP6).

Drives one task from creation to a terminal TaskResult through the real Phase-4
application services wired with a deterministic stub worker, then verifies the
durable evidence (single run, finalized result, idempotency). This is explicitly a
verification scenario — never presented as an AI-generated production task.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ant_orchestrator.application.errors import WorkflowStateError
from ant_orchestrator.application.models.result_views import TaskResultView
from ant_orchestrator.cli.composition_self_test import SelfTestComposition
from ant_orchestrator.cli.cp5_doctor_checks import (
    STATUS_FAIL,
    STATUS_PASS,
    STATUS_SKIP,
    CheckResult,
)
from ant_orchestrator.cli.self_test_artifact import (
    SELF_TEST_ARTIFACT_CONTENT,
    SELF_TEST_ARTIFACT_RELATIVE_PATH,
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
    results.append(_artifact_digest_check(view, composition.artifacts_root))
    count = _count(composition, "task_results", task_id)
    results.append(
        CheckResult(
            "result.no_duplicate",
            STATUS_PASS if count == 1 else STATUS_FAIL,
            f"{count} result row(s) for task",
        )
    )
    return results


def _artifact_digest_check(view: TaskResultView, artifacts_root: Path) -> CheckResult:
    """Verify the persisted self-test artifact end-to-end (digest, path safety, content).

    The self-test composition writes exactly one deterministic internal artifact, so a
    missing or mismatching ref is a real failure — never a SKIP.
    """
    refs = view.artifact_refs
    if len(refs) != 1:
        return CheckResult(
            "result.artifact_digest", STATUS_FAIL, f"expected 1 artifact ref, found {len(refs)}"
        )
    ref = refs[0]
    rel = ref.relative_path
    if rel != SELF_TEST_ARTIFACT_RELATIVE_PATH or rel.startswith(("/", "\\")) or ".." in rel:
        return CheckResult("result.artifact_digest", STATUS_FAIL, "unsafe/unexpected artifact path")

    expected = SELF_TEST_ARTIFACT_CONTENT.encode("utf-8")
    root = artifacts_root.resolve()
    target = (artifacts_root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        return CheckResult("result.artifact_digest", STATUS_FAIL, "artifact escaped artifacts root")
    if not target.is_file():
        return CheckResult("result.artifact_digest", STATUS_FAIL, "artifact file missing on disk")

    on_disk = target.read_bytes()
    sha = hashlib.sha256(on_disk).hexdigest()
    if (
        on_disk != expected
        or ref.size_bytes != len(expected)
        or ref.sha256 != sha
        or len(ref.sha256) != 64
    ):
        return CheckResult("result.artifact_digest", STATUS_FAIL, "artifact digest/size mismatch")
    return CheckResult(
        "result.artifact_digest", STATUS_PASS, f"internal artifact verified ({ref.size_bytes} B)"
    )


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
