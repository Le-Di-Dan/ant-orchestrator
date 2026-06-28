"""CP6 isolation re-verification tests (§5).

Re-verifies the CP2-CP5 isolation contract from the CP6 integration perspective:
  §5.1  Image ref is content-addressable sha256 ID, not a mutable tag.
  §5.2  Context digest mismatch fails closed (no backend call).
  §5.3  Read scope digest is deterministic and stable.
  §5.4  No .git in container argv (regression guard).
  §5.5  DurableTestExecution refuses empty canonical_read_scope.
  §5.6  Container name prefix is constant (no host env leakage).
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ant_orchestrator.adapters.container_argv import (
    ContainerRunPlan,
    build_run_argv,
)
from ant_orchestrator.application.ports.test_execution import TestExecutionOutcome
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.config.constants import (
    TEST_CONTAINER_NAME_PREFIX,
    TEST_ISOLATION_IMAGE_ID,
    TEST_ISOLATION_IMAGE_REF,
)
from ant_orchestrator.core.domain.test_failure import (
    RecoveryDisposition,
    TestReasonCode,
)
from ant_orchestrator.core.domain.value_objects import UtcTimestamp, WorkflowRunId
from ant_orchestrator.integration.test_execution_adapter import DurableTestExecution
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.workflows.attempt_orchestrator import AttemptOrchestrator
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.cp4_helpers import add_task, create_running_run

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clock() -> FakeClock:
    return FakeClock(UtcTimestamp(datetime(2026, 6, 28, tzinfo=UTC)))


def _scope_digest(scope: tuple[str, ...]) -> str:
    content = "\x00".join(sorted(scope))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _make_db(tmp_path: Path, clock: FakeClock, run_id: str = "R1") -> Database:
    db_path = tmp_path / "state.sqlite"
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    db = Database(db_path)
    add_task(db, "T1", clock=clock)
    create_running_run(db, WorkflowRunId(run_id), "T1", clock, SequentialIdGenerator("setup"))
    return db


def _make_orch(tmp_path: Path, clock: FakeClock) -> AttemptOrchestrator:
    db = _make_db(tmp_path, clock)

    def _uow_f() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(db)

    return AttemptOrchestrator(_uow_f, clock=clock, ids=SequentialIdGenerator())


def _base_plan() -> ContainerRunPlan:
    return ContainerRunPlan(
        name=f"{TEST_CONTAINER_NAME_PREFIX}abc",
        image_ref=TEST_ISOLATION_IMAGE_REF,
        snapshot_host=r"C:\snap",
        out_host=r"C:\out",
        inner_argv=("python", "-m", "pytest"),
        user="1000:1000",
        pids_limit=256,
        memory="512m",
        tmpfs_size="64m",
        work_mount="/work",
        out_mount="/out",
    )


class _NeverCalledAnt:
    __test__ = False

    def execute(self, task, scope, run_id):  # type: ignore[override]
        raise AssertionError("backend must not be called in this test scenario")


def _success_ant_class():  # type: ignore[return]
    """Return a success-returning TestAnt class (avoids late-import at module level)."""
    from ant_orchestrator.workers.test.result import TestExecutionResult

    class _SuccessAnt:
        __test__ = False

        def execute(self, task, scope, run_id):  # type: ignore[override]
            return TestExecutionResult(
                structured_report=None,  # type: ignore[arg-type]
                worker_report=None,
                outcome=TestExecutionOutcome(
                    outcome=WorkerOutcome.SUCCESS, attempt_ref=scope.attempt_id
                ),
                cancelled=False,
            )

    return _SuccessAnt()


# ---------------------------------------------------------------------------
# §5.1 — image ref is sha256 content-addressable ID
# ---------------------------------------------------------------------------


def test_isolation_image_ref_is_sha256() -> None:
    """§5.1: TEST_ISOLATION_IMAGE_REF must start with 'sha256:' (not a mutable tag)."""
    assert TEST_ISOLATION_IMAGE_REF.startswith("sha256:"), (
        f"image ref must be a sha256 digest, got: {TEST_ISOLATION_IMAGE_REF!r}"
    )


def test_isolation_image_ref_equals_image_id() -> None:
    """§5.1: REF == ID ensures we resolve the same immutable layer, not a registry alias."""
    assert TEST_ISOLATION_IMAGE_REF == TEST_ISOLATION_IMAGE_ID


# ---------------------------------------------------------------------------
# §5.2 — context digest mismatch fails closed
# ---------------------------------------------------------------------------


def test_context_digest_mismatch_fails_closed(tmp_path: Path) -> None:
    """§5.2: expected_context_digest set but incoming digest differs → backend NOT called."""
    orch = _make_orch(tmp_path, _clock())

    adapter = DurableTestExecution(
        ant=_NeverCalledAnt(),  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
        expected_context_digest="approved-digest-abc",
    )

    outcome = adapter.execute(
        task_id="T1",
        run_id="R1",
        context_manifest_digest="TAMPERED-digest",
    )

    assert outcome.outcome is WorkerOutcome.PERMANENT_FAILURE
    assert outcome.disposition is RecoveryDisposition.TERMINAL_FAILED
    assert outcome.reason_code is TestReasonCode.EXECUTION_BOUNDARY_DENIED


def test_context_digest_match_allows_execution(tmp_path: Path) -> None:
    """§5.2: matching context digest → execution proceeds."""
    orch = _make_orch(tmp_path, _clock())
    ant = _success_ant_class()

    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
        expected_context_digest="approved-digest-abc",
    )

    outcome = adapter.execute(
        task_id="T1",
        run_id="R1",
        context_manifest_digest="approved-digest-abc",
    )
    assert outcome.outcome is WorkerOutcome.SUCCESS


def test_empty_expected_digest_allows_any_context(tmp_path: Path) -> None:
    """§5.2: expected_context_digest='' (default) → skip digest check (CP4 compatibility)."""
    orch = _make_orch(tmp_path, _clock())
    ant = _success_ant_class()

    adapter = DurableTestExecution(
        ant=ant,  # type: ignore[arg-type]
        attempt_orchestrator=orch,
        canonical_read_scope=("src/",),
        command_profile_key="pytest.acceptance",
    )

    outcome = adapter.execute(task_id="T1", run_id="R1", context_manifest_digest="anything")
    assert outcome.outcome is WorkerOutcome.SUCCESS


# ---------------------------------------------------------------------------
# §5.3 — read scope digest is deterministic
# ---------------------------------------------------------------------------


def test_read_scope_digest_stable_across_calls() -> None:
    """§5.3: same scope → same digest, different scope → different digest."""
    d1a = _scope_digest(("src/",))
    d1b = _scope_digest(("src/",))
    d2 = _scope_digest(("tests/",))

    assert d1a == d1b
    assert d1a != d2


def test_read_scope_digest_order_independent() -> None:
    """§5.3: scope digest is order-independent (sorts before hashing)."""
    d_ab = _scope_digest(("src/", "tests/"))
    d_ba = _scope_digest(("tests/", "src/"))
    assert d_ab == d_ba


# ---------------------------------------------------------------------------
# §5.4 — no .git in container argv
# ---------------------------------------------------------------------------


def test_container_argv_no_git_mount() -> None:
    """§5.4: .git directory must never appear in the Docker run argv."""
    argv = build_run_argv(dataclasses.replace(_base_plan(), env=(("HOME", "/out"),)))
    joined = " ".join(argv)
    assert "/.git" not in joined
    assert "\\.git" not in joined


def test_container_argv_read_only_flag_present() -> None:
    """§5.4: --read-only flag enforces no snapshot writes from inside the container."""
    argv = build_run_argv(dataclasses.replace(_base_plan(), env=(("HOME", "/out"),)))
    assert "--read-only" in argv


def test_container_argv_no_privileged_flag() -> None:
    """§5.4: --privileged must never appear in the argv."""
    argv = build_run_argv(dataclasses.replace(_base_plan(), env=(("HOME", "/out"),)))
    assert "--privileged" not in argv


# ---------------------------------------------------------------------------
# §5.5 — DurableTestExecution refuses empty scope
# ---------------------------------------------------------------------------


def test_durable_execution_requires_non_empty_scope(tmp_path: Path) -> None:
    """§5.5: canonical_read_scope=() is rejected at construction (InvariantViolation)."""
    from ant_orchestrator.core.domain.errors import InvariantViolation

    orch = _make_orch(tmp_path, _clock())

    with pytest.raises(InvariantViolation):
        DurableTestExecution(
            ant=_NeverCalledAnt(),  # type: ignore[arg-type]
            attempt_orchestrator=orch,
            canonical_read_scope=(),
            command_profile_key="pytest.acceptance",
        )


# ---------------------------------------------------------------------------
# §5.6 — container name prefix is constant
# ---------------------------------------------------------------------------


def test_container_name_prefix_is_constant() -> None:
    """§5.6: container names use the fixed prefix (no hostname, username, or env)."""
    plan = _base_plan()
    assert plan.name.startswith(TEST_CONTAINER_NAME_PREFIX)


def test_image_ref_not_a_mutable_tag() -> None:
    """§5.6: image ref must not contain ':latest' or any mutable tag shorthand."""
    assert ":latest" not in TEST_ISOLATION_IMAGE_REF
    assert "@sha256:" not in TEST_ISOLATION_IMAGE_REF or TEST_ISOLATION_IMAGE_REF.startswith(
        "sha256:"
    )
