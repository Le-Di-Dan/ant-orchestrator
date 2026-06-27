"""CP4 tests — durable single-document mutation, artifacts, journal, recovery.

Covers permission ordering (A), CREATE/UPDATE happy paths (B/C), operation semantics
(D), validation (E), diff (F), artifact root (G), journal lifecycle (H), the recovery
matrix (I/J), symlink TOCTOU (K), atomic durability (L), and no-leak (M). Recovery is a
pure decider — it never needs the LLM (none exists in CP4).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.config.constants import (
    JOURNAL_SCHEMA_VERSION,
    MAX_ARTIFACT_BYTES,
)
from ant_orchestrator.execution.document_mutator import SafeDocumentMutator
from ant_orchestrator.execution.document_validation import DocumentValidator, ValidationFailure
from ant_orchestrator.execution.mutation_artifacts import (
    ArtifactCorrupt,
    ArtifactKind,
    ArtifactRoot,
    ArtifactRootViolation,
    ArtifactTooLarge,
    BeforeState,
    read_artifact,
    write_artifact,
)
from ant_orchestrator.execution.mutation_recovery import (
    DbObservation,
    MutationRecovery,
    RecoveryAction,
    TargetKind,
    TargetObservation,
)
from ant_orchestrator.execution.mutation_types import MutationOutcome, MutationRequest
from ant_orchestrator.execution.prepared_mutation import (
    InvalidJournalTransition,
    JournalConflict,
    JournalCorrupt,
    JournalStatus,
    JournalStore,
    MutationJournal,
    UnsupportedJournalVersion,
)
from ant_orchestrator.security.path_policy import PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.security.protected_paths import PROTECTED_POLICY_VERSION

_HANDOFF = "docs/handoffs/HANDOFF-001.md"


def _artifacts_root(ws: Path) -> Path:
    return ws / ".ant" / "artifacts"


def _mutator(
    ws: Path, *, wide: bool = False, version: int = PROTECTED_POLICY_VERSION
) -> SafeDocumentMutator:
    write_root = ws if wide else ws / "docs" / "handoffs"
    write_root.mkdir(parents=True, exist_ok=True)
    scope = PathScope.build(read_roots=(), write_roots=(write_root,))
    policy = ProtectedPathPolicy(
        scope=scope, workspace_root=ws, policy_version=version, case_insensitive=False
    )
    return SafeDocumentMutator(policy=policy, workspace_root=ws, artifacts_root=_artifacts_root(ws))


def _content(sections: tuple[str, ...] = ("Summary",)) -> str:
    return "\n".join(f"# {s}\n\nbody for {s}" for s in sections)


def _request(
    *,
    target: str = _HANDOFF,
    operation: DocumentOperation = DocumentOperation.CREATE,
    content: str | None = None,
    sections: tuple[str, ...] = ("Summary",),
    version: int = PROTECTED_POLICY_VERSION,
    attempt: str = "attempt-1",
) -> MutationRequest:
    return MutationRequest(
        run_id="run-1",
        attempt_id=attempt,
        logical_action_id="act-1",
        proposal_digest="proposal-digest",
        context_digest="context-digest",
        approval_ref="approval-1",
        requested_target=target,
        operation=operation,
        proposed_content=content if content is not None else _content(sections),
        required_sections=sections,
        protected_policy_version=version,
    )


def _load_journal(ws: Path, request: MutationRequest) -> MutationJournal:
    roots = ArtifactRoot(_artifacts_root(ws), request.run_id, request.attempt_id)
    return JournalStore(roots.path_for(ArtifactKind.JOURNAL)).load()


# --- A. permission ordering ------------------------------------------------


def test_protected_target_denied_no_artifacts(tmp_path: Path) -> None:
    (tmp_path / "ROADMAP.md").write_text("orig", encoding="utf-8")
    result = _mutator(tmp_path, wide=True).execute(
        _request(target="ROADMAP.md", operation=DocumentOperation.UPDATE)
    )
    assert result.outcome is MutationOutcome.PERMISSION_DENIED
    assert result.permission_reason == "protected_document"
    assert not _artifacts_root(tmp_path).exists()  # nothing read/written for the target
    assert (tmp_path / "ROADMAP.md").read_text(encoding="utf-8") == "orig"


def test_policy_version_mismatch_fails_closed(tmp_path: Path) -> None:
    result = _mutator(tmp_path, version=1).execute(_request(version=2))
    assert result.outcome is MutationOutcome.PERMISSION_DECISION_INVALID
    assert not _artifacts_root(tmp_path).exists()


def test_journal_canonical_target_matches_decision(tmp_path: Path) -> None:
    request = _request()
    result = _mutator(tmp_path).execute(request)
    assert result.outcome is MutationOutcome.PUBLISHED
    assert _load_journal(tmp_path, request).canonical_target == result.canonical_target


# --- B. CREATE happy path --------------------------------------------------


def test_create_happy_path(tmp_path: Path) -> None:
    request = _request(operation=DocumentOperation.CREATE)
    result = _mutator(tmp_path).execute(request)
    assert result.outcome is MutationOutcome.PUBLISHED
    assert result.before_kind == "absent"
    target = tmp_path / _HANDOFF
    assert target.read_text(encoding="utf-8") == request.proposed_content
    assert result.target_digest == hashlib.sha256(target.read_bytes()).hexdigest()
    assert _load_journal(tmp_path, request).status == JournalStatus.PUBLISHED.value


def test_create_diff_shows_new_file(tmp_path: Path) -> None:
    request = _request(operation=DocumentOperation.CREATE)
    result = _mutator(tmp_path).execute(request)
    roots = ArtifactRoot(_artifacts_root(tmp_path), request.run_id, request.attempt_id)
    diff = read_artifact(roots.path_for(ArtifactKind.DIFF), result.diff_digest or "")
    assert "/dev/null" in diff
    assert f"b/{_HANDOFF}" in diff
    assert str(tmp_path) not in diff  # no host absolute path leaks


# --- C. UPDATE happy path --------------------------------------------------


def test_update_happy_path(tmp_path: Path) -> None:
    target = tmp_path / _HANDOFF
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Summary\n\nold body", encoding="utf-8")
    before_digest = hashlib.sha256(target.read_bytes()).hexdigest()
    request = _request(operation=DocumentOperation.UPDATE, content="# Summary\n\nnew body")
    result = _mutator(tmp_path).execute(request)
    assert result.outcome is MutationOutcome.PUBLISHED
    assert result.before_kind == "present"
    journal = _load_journal(tmp_path, request)
    assert journal.previous_digest == before_digest
    assert target.read_text(encoding="utf-8") == "# Summary\n\nnew body"
    roots = ArtifactRoot(_artifacts_root(tmp_path), request.run_id, request.attempt_id)
    assert roots.path_for(ArtifactKind.BEFORE).exists()  # before snapshot retained


# --- D. operation semantics ------------------------------------------------


def test_create_on_existing_fails(tmp_path: Path) -> None:
    (tmp_path / _HANDOFF).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / _HANDOFF).write_text("exists", encoding="utf-8")
    result = _mutator(tmp_path).execute(_request(operation=DocumentOperation.CREATE))
    assert result.outcome is MutationOutcome.TARGET_EXISTS
    assert (tmp_path / _HANDOFF).read_text(encoding="utf-8") == "exists"  # not overwritten


def test_update_on_absent_fails(tmp_path: Path) -> None:
    result = _mutator(tmp_path).execute(_request(operation=DocumentOperation.UPDATE))
    assert result.outcome is MutationOutcome.TARGET_MISSING
    assert not (tmp_path / _HANDOFF).exists()  # not created


def test_update_on_directory_fails(tmp_path: Path) -> None:
    target = tmp_path / _HANDOFF
    target.mkdir(parents=True, exist_ok=True)
    result = _mutator(tmp_path).execute(_request(operation=DocumentOperation.UPDATE))
    # A directory target is rejected fail-closed (permission layer NOT_A_FILE, or
    # the mutator's own TARGET_NOT_FILE) — never published, directory untouched.
    assert result.outcome in (
        MutationOutcome.PERMISSION_DENIED,
        MutationOutcome.TARGET_NOT_FILE,
    )
    assert target.is_dir()


def test_no_batch_api() -> None:
    assert not hasattr(SafeDocumentMutator, "mutate_many")
    assert not hasattr(SafeDocumentMutator, "batch_publish")


# --- E. validation ---------------------------------------------------------


@pytest.mark.parametrize(
    "content,sections",
    [
        ("", ("Summary",)),
        ("# Other\n\nbody", ("Summary",)),
        ("# Summary\n\na\n# Summary\n\nb", ("Summary",)),
        ("# Summary\n\nbody\x00", ("Summary",)),
    ],
)
def test_validation_failure_no_mutation(
    tmp_path: Path, content: str, sections: tuple[str, ...]
) -> None:
    result = _mutator(tmp_path).execute(
        _request(operation=DocumentOperation.CREATE, content=content, sections=sections)
    )
    assert result.outcome is MutationOutcome.VALIDATION_FAILED
    assert result.validation_failures
    assert not (tmp_path / _HANDOFF).exists()
    assert not _artifacts_root(tmp_path).exists()  # no PREPARED journal


def test_validator_unit() -> None:
    v = DocumentValidator()
    assert v.validate("# Summary\n\nx", ("Summary",)).ok
    assert ValidationFailure.MISSING_SECTION in v.validate("x", ("Summary",)).failures


# --- F. diff ---------------------------------------------------------------


def test_noop_update_returns_no_change(tmp_path: Path) -> None:
    target = tmp_path / _HANDOFF
    target.parent.mkdir(parents=True, exist_ok=True)
    same = "# Summary\n\nsame"
    target.write_text(same, encoding="utf-8")
    result = _mutator(tmp_path).execute(_request(operation=DocumentOperation.UPDATE, content=same))
    assert result.outcome is MutationOutcome.NO_CHANGE
    assert not _artifacts_root(tmp_path).exists()  # no publish, no journal


def test_diff_digest_verifies(tmp_path: Path) -> None:
    request = _request()
    result = _mutator(tmp_path).execute(request)
    roots = ArtifactRoot(_artifacts_root(tmp_path), request.run_id, request.attempt_id)
    text = roots.path_for(ArtifactKind.DIFF).read_text(encoding="utf-8")
    assert hashlib.sha256(text.encode("utf-8")).hexdigest() == result.diff_digest


# --- G. artifact root ------------------------------------------------------


def test_artifacts_outside_write_scope(tmp_path: Path) -> None:
    request = _request()
    _mutator(tmp_path).execute(request)
    roots = ArtifactRoot(_artifacts_root(tmp_path), request.run_id, request.attempt_id)
    # artifacts live under .ant/artifacts, never under the docs/handoffs write scope
    assert ".ant" in roots.attempt_dir().relative_to(tmp_path).parts
    assert "docs" not in roots.attempt_dir().relative_to(tmp_path).parts


def test_artifact_root_rejects_escape(tmp_path: Path) -> None:
    roots = ArtifactRoot(_artifacts_root(tmp_path), "run", "attempt")
    with pytest.raises(ArtifactRootViolation):
        roots.resolve_ref("../../etc/passwd")


def test_write_artifact_oversize_rejected(tmp_path: Path) -> None:
    path = tmp_path / "big.txt"
    with pytest.raises(ArtifactTooLarge):
        write_artifact(path, "x" * (MAX_ARTIFACT_BYTES + 1))


def test_read_artifact_missing_and_tampered(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    digest = write_artifact(path, "hello")
    read_artifact(path, digest)  # ok
    path.write_text("tampered", encoding="utf-8")
    with pytest.raises(ArtifactCorrupt):
        read_artifact(path, digest)
    with pytest.raises(ArtifactCorrupt):
        read_artifact(tmp_path / "missing.txt", digest)


# --- H. journal ------------------------------------------------------------


def _journal(
    status: JournalStatus,
    *,
    before_kind: str = "present",
    previous: str | None = "prev-d",
    proposed: str = "prop-d",
    operation: str = "update",
) -> MutationJournal:
    return MutationJournal(
        schema_version=JOURNAL_SCHEMA_VERSION,
        run_id="run-1",
        attempt_id="attempt-1",
        logical_action_id="act-1",
        proposal_digest="pd",
        approval_ref="",
        context_digest="cd",
        canonical_target="docs/handoffs/x.md",
        operation=operation,
        protected_policy_version=1,
        before_kind=before_kind,
        previous_digest=previous,
        proposed_digest=proposed,
        before_ref="run/att/before.json",
        before_digest="bd",
        proposed_ref="run/att/proposed.txt",
        proposed_digest_ref=proposed,
        diff_ref="run/att/diff.patch",
        diff_digest="dd",
        validation_ok=True,
        status=status.value,
        revision=0,
    )


def test_journal_roundtrip_and_checksum(tmp_path: Path) -> None:
    store = JournalStore(tmp_path / "j.json")
    store.save(_journal(JournalStatus.PREPARED))
    assert store.load().status == JournalStatus.PREPARED.value
    document = json.loads((tmp_path / "j.json").read_text(encoding="utf-8"))
    document["checksum"] = "deadbeef"
    (tmp_path / "j.json").write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(JournalCorrupt):
        store.load()


def test_journal_transitions() -> None:
    prepared = _journal(JournalStatus.PREPARED)
    published = prepared.advance_to(JournalStatus.PUBLISHED)
    assert published.status == JournalStatus.PUBLISHED.value
    assert published.advance_to(JournalStatus.COMPLETED).status == JournalStatus.COMPLETED.value
    assert published.advance_to(JournalStatus.PUBLISHED) is published  # idempotent
    with pytest.raises(InvalidJournalTransition):
        published.advance_to(JournalStatus.PREPARED)  # backward
    with pytest.raises(InvalidJournalTransition):
        prepared.advance_to(JournalStatus.COMPLETED)  # skip


def test_unsupported_journal_version() -> None:
    doc = json.loads(_journal(JournalStatus.PREPARED).to_json())
    doc["schema_version"] = 999
    with pytest.raises(UnsupportedJournalVersion):
        MutationJournal.from_document(doc)


def test_journal_has_no_raw_payload() -> None:
    text = _journal(JournalStatus.PREPARED).to_json().lower()
    for banned in ("prompt", "response", "exception", "traceback"):
        assert banned not in text


# --- I. recovery matrix ----------------------------------------------------


def test_recovery_no_journal_fresh() -> None:
    d = MutationRecovery().decide(None, TargetObservation(TargetKind.ABSENT), DbObservation())
    assert d.action is RecoveryAction.FRESH_EXECUTE
    assert d.requires_llm is False


def test_recovery_prepared_states() -> None:
    rec = MutationRecovery()
    prepared = _journal(JournalStatus.PREPARED, previous="prev-d", proposed="prop-d")
    at_prev = TargetObservation(TargetKind.PRESENT, "prev-d")
    at_prop = TargetObservation(TargetKind.PRESENT, "prop-d")
    other = TargetObservation(TargetKind.PRESENT, "other-d")
    assert (
        rec.decide(prepared, at_prev, DbObservation()).action is RecoveryAction.PUBLISH_THEN_VERIFY
    )
    assert rec.decide(prepared, at_prop, DbObservation()).action is RecoveryAction.MARK_PUBLISHED
    assert rec.decide(prepared, other, DbObservation()).action is RecoveryAction.FAIL_CONFLICT


def test_recovery_create_prepared_absent() -> None:
    prepared = _journal(
        JournalStatus.PREPARED, before_kind="absent", previous=None, operation="create"
    )
    d = MutationRecovery().decide(prepared, TargetObservation(TargetKind.ABSENT), DbObservation())
    assert d.action is RecoveryAction.PUBLISH_THEN_VERIFY


def test_recovery_published_states() -> None:
    rec = MutationRecovery()
    published = _journal(JournalStatus.PUBLISHED, proposed="prop-d")
    at_prop = TargetObservation(TargetKind.PRESENT, "prop-d")
    mismatch = TargetObservation(TargetKind.PRESENT, "other-d")
    assert rec.decide(published, at_prop, DbObservation(False)).action is (
        RecoveryAction.PERSIST_EXECUTION_RECORDS
    )
    assert rec.decide(published, at_prop, DbObservation(True)).action is (
        RecoveryAction.FINALIZE_COMPLETED
    )
    assert rec.decide(published, mismatch, DbObservation(True)).action is (
        RecoveryAction.FAIL_TARGET_MISMATCH
    )


def test_recovery_completed_noop() -> None:
    completed = _journal(JournalStatus.COMPLETED, proposed="prop-d")
    d = MutationRecovery().decide(
        completed, TargetObservation(TargetKind.PRESENT, "prop-d"), DbObservation(True)
    )
    assert d.action is RecoveryAction.NOOP


def test_recovery_from_published_mutation_no_llm(tmp_path: Path) -> None:
    # End-to-end: publish, then recover from the persisted journal + observed target.
    request = _request()
    result = _mutator(tmp_path).execute(request)
    journal = _load_journal(tmp_path, request)
    target = tmp_path / _HANDOFF
    observed = TargetObservation(
        TargetKind.PRESENT, hashlib.sha256(target.read_bytes()).hexdigest()
    )
    decision = MutationRecovery().decide(journal, observed, DbObservation(False))
    assert decision.action is RecoveryAction.PERSIST_EXECUTION_RECORDS
    assert decision.requires_llm is False
    assert result.target_digest == observed.digest


# --- K. symlink TOCTOU -----------------------------------------------------


def _symlinks_supported(tmp_path: Path) -> bool:
    link = tmp_path / "_probe"
    try:
        link.symlink_to(tmp_path)
    except (OSError, NotImplementedError):
        return False
    link.unlink()
    return True


def test_update_symlink_target_unsafe(tmp_path: Path) -> None:
    if not _symlinks_supported(tmp_path):
        pytest.skip("platform cannot create symlinks")
    (tmp_path / "docs/handoffs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "real.md").write_text("# Summary\n\nreal", encoding="utf-8")
    (tmp_path / _HANDOFF).symlink_to(tmp_path / "real.md")
    result = _mutator(tmp_path).execute(_request(operation=DocumentOperation.UPDATE))
    assert result.outcome is MutationOutcome.TARGET_NOT_FILE


# --- L. atomic durability --------------------------------------------------


def test_publish_leaves_no_staging(tmp_path: Path) -> None:
    request = _request()
    _mutator(tmp_path).execute(request)
    parent = (tmp_path / _HANDOFF).parent
    assert not any(p.name.endswith(".ant-pub.tmp") for p in parent.iterdir())


# --- M. no-leak ------------------------------------------------------------


def test_before_artifact_has_no_raw_exception(tmp_path: Path) -> None:
    target = tmp_path / _HANDOFF
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("# Summary\n\nold", encoding="utf-8")
    request = _request(operation=DocumentOperation.UPDATE, content="# Summary\n\nnew")
    _mutator(tmp_path).execute(request)
    roots = ArtifactRoot(_artifacts_root(tmp_path), request.run_id, request.attempt_id)
    before = roots.path_for(ArtifactKind.BEFORE).read_text(encoding="utf-8").lower()
    assert "traceback" not in before and "exception" not in before


def test_before_state_typed_absent() -> None:
    absent = BeforeState.absent()
    assert absent.content is None and absent.digest is None


def test_journal_conflict_type_exists() -> None:
    # JournalConflict is part of the taxonomy CP6 recovery uses.
    assert issubclass(JournalConflict, Exception)
