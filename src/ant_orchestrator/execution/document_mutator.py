"""SafeDocumentMutator — durable single-document CREATE/UPDATE (PHASE_5_PLAN CP4 / D.2).

Enforces the fresh-execution ordering: permission preflight (CP3) BEFORE any read; the
canonical target comes only from an ``ALLOW`` decision; before-state capture; deterministic
validation BEFORE publish; before/proposed/diff artifacts persisted + digest-verified; a
durable ``PREPARED`` journal written BEFORE the target changes; a publish-time symlink/
permission recheck and external-mutation guard; atomic flushed publish; target-digest
verification; then journal ``PUBLISHED``. DB persistence and ``COMPLETED`` belong to CP6.
No model output is trusted; no raw prompt/response/exception is ever persisted.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.config.constants import JOURNAL_SCHEMA_VERSION, MAX_BEFORE_READ_BYTES
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.execution.document_diff import build_document_diff
from ant_orchestrator.execution.document_validation import DocumentValidator
from ant_orchestrator.execution.mutation_artifacts import (
    ArtifactKind,
    ArtifactRoot,
    BeforeState,
    fsync_dir,
    read_artifact,
    sha256_text,
    write_artifact,
)
from ant_orchestrator.execution.mutation_types import (
    MutationOutcome,
    MutationRequest,
    MutationResult,
)
from ant_orchestrator.execution.prepared_mutation import (
    JournalStatus,
    JournalStore,
    MutationJournal,
)
from ant_orchestrator.security.path_policy import PathAccess
from ant_orchestrator.security.protected_path_policy import (
    ProtectedPathDecision,
    ProtectedPathPolicy,
)

_PUBLISH_SUFFIX = ".ant-pub.tmp"


class SafeDocumentMutator:
    """The only path through which a worker may mutate a document (I1)."""

    def __init__(
        self,
        *,
        policy: ProtectedPathPolicy,
        workspace_root: Path,
        artifacts_root: Path,
        validator: DocumentValidator | None = None,
    ) -> None:
        self._policy = policy
        self._ws = workspace_root.resolve()
        self._artifacts_root = artifacts_root
        self._validator = validator if validator is not None else DocumentValidator()

    def execute(self, request: MutationRequest) -> MutationResult:
        decision = self._policy.check(request.requested_target, PathAccess.WRITE)
        if decision.decision is not PolicyDecision.ALLOW:
            reason = decision.reason.value if decision.reason else "denied"
            return self._fail(request, MutationOutcome.PERMISSION_DENIED, permission_reason=reason)
        if decision.canonical_relpath is None or (
            decision.protected_policy_version != request.protected_policy_version
        ):
            return self._fail(request, MutationOutcome.PERMISSION_DECISION_INVALID)

        relpath = decision.canonical_relpath
        target = self._ws / Path(relpath)
        before, failure = self._read_before(request, target)
        if failure is not None:
            return failure

        validation = self._validator.validate(request.proposed_content, request.required_sections)
        if not validation.ok:
            return self._fail(
                request,
                MutationOutcome.VALIDATION_FAILED,
                canonical_target=relpath,
                validation_failures=tuple(f.value for f in validation.failures),
            )

        assert before is not None
        proposed_digest = sha256_text(request.proposed_content)
        diff = build_document_diff(before, request.proposed_content, relpath)
        if diff.no_change:
            return self._fail(request, MutationOutcome.NO_CHANGE, canonical_target=relpath)

        roots = ArtifactRoot(self._artifacts_root, request.run_id, request.attempt_id)
        digests = self._persist_artifacts(roots, before, request.proposed_content, diff.text)
        journal = self._build_journal(request, relpath, before, proposed_digest, roots, digests)
        store = JournalStore(roots.path_for(ArtifactKind.JOURNAL))
        store.save(journal)

        conflict = self._guard_before_publish(request, decision, relpath, target, before)
        if conflict is not None:
            return self._conflict(request, relpath, roots, conflict)

        self._publish(target, request.proposed_content)
        if self._digest_of(target) != proposed_digest:
            return self._conflict(request, relpath, roots, "target digest changed after publish")

        store.save(journal.advance_to(JournalStatus.PUBLISHED))
        return self._published(request, relpath, before, proposed_digest, roots, digests)

    # --- before-state --------------------------------------------------------
    def _read_before(
        self, request: MutationRequest, target: Path
    ) -> tuple[BeforeState | None, MutationResult | None]:
        is_symlink = target.is_symlink()
        if request.operation is DocumentOperation.CREATE:
            if is_symlink or target.exists():
                return None, self._fail(request, MutationOutcome.TARGET_EXISTS)
            return BeforeState.absent(), None
        if is_symlink:
            return None, self._fail(request, MutationOutcome.TARGET_NOT_FILE)
        if not target.exists():
            return None, self._fail(request, MutationOutcome.TARGET_MISSING)
        if not target.is_file():
            return None, self._fail(request, MutationOutcome.TARGET_NOT_FILE)
        content = self._read_text(target)
        if content is None:
            return None, self._fail(request, MutationOutcome.TARGET_NOT_FILE)
        return BeforeState.present(content), None

    @staticmethod
    def _read_text(target: Path) -> str | None:
        try:
            data = target.read_bytes()
        except OSError:
            return None
        if len(data) > MAX_BEFORE_READ_BYTES or b"\x00" in data:
            return None
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError:
            return None

    # --- artifacts + journal -------------------------------------------------
    def _persist_artifacts(
        self, roots: ArtifactRoot, before: BeforeState, proposed: str, diff_text: str
    ) -> dict[ArtifactKind, str]:
        before_json = json.dumps(
            {"kind": before.kind.value, "digest": before.digest, "content": before.content},
            ensure_ascii=False,
            sort_keys=True,
        )
        digests = {
            ArtifactKind.BEFORE: write_artifact(roots.path_for(ArtifactKind.BEFORE), before_json),
            ArtifactKind.PROPOSED: write_artifact(roots.path_for(ArtifactKind.PROPOSED), proposed),
            ArtifactKind.DIFF: write_artifact(roots.path_for(ArtifactKind.DIFF), diff_text),
        }
        for kind, digest in digests.items():
            read_artifact(roots.path_for(kind), digest)  # verify each artifact round-trips
        return digests

    def _build_journal(
        self,
        request: MutationRequest,
        relpath: str,
        before: BeforeState,
        proposed_digest: str,
        roots: ArtifactRoot,
        digests: dict[ArtifactKind, str],
    ) -> MutationJournal:
        return MutationJournal(
            schema_version=JOURNAL_SCHEMA_VERSION,
            run_id=request.run_id,
            attempt_id=request.attempt_id,
            logical_action_id=request.logical_action_id,
            proposal_digest=request.proposal_digest,
            approval_ref=request.approval_ref,
            context_digest=request.context_digest,
            canonical_target=relpath,
            operation=request.operation.value,
            protected_policy_version=request.protected_policy_version,
            before_kind=before.kind.value,
            previous_digest=before.digest,
            proposed_digest=proposed_digest,
            before_ref=roots.ref_for(ArtifactKind.BEFORE),
            before_digest=digests[ArtifactKind.BEFORE],
            proposed_ref=roots.ref_for(ArtifactKind.PROPOSED),
            proposed_digest_ref=digests[ArtifactKind.PROPOSED],
            diff_ref=roots.ref_for(ArtifactKind.DIFF),
            diff_digest=digests[ArtifactKind.DIFF],
            validation_ok=True,
            status=JournalStatus.PREPARED.value,
            revision=0,
        )

    # --- publish -------------------------------------------------------------
    def _guard_before_publish(
        self,
        request: MutationRequest,
        decision: ProtectedPathDecision,
        relpath: str,
        target: Path,
        before: BeforeState,
    ) -> str | None:
        recheck = self._policy.check(request.requested_target, PathAccess.WRITE)
        if recheck.decision is not PolicyDecision.ALLOW or recheck.canonical_relpath != relpath:
            return "permission/symlink changed before publish"
        if request.operation is DocumentOperation.CREATE:
            if target.is_symlink() or target.exists():
                return "target appeared before publish"
            return None
        if target.is_symlink() or not target.is_file():
            return "target became unsafe before publish"
        current = self._read_text(target)
        if current is None or sha256_text(current) != before.digest:
            return "target changed before publish"
        return None

    def _publish(self, target: Path, content: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.parent / (target.name + _PUBLISH_SUFFIX)
        with open(tmp, "wb") as handle:
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        fsync_dir(target.parent)

    @staticmethod
    def _digest_of(target: Path) -> str:
        return hashlib.sha256(target.read_bytes()).hexdigest()

    # --- result builders -----------------------------------------------------
    def _published(
        self,
        request: MutationRequest,
        relpath: str,
        before: BeforeState,
        proposed_digest: str,
        roots: ArtifactRoot,
        digests: dict[ArtifactKind, str],
    ) -> MutationResult:
        return MutationResult(
            outcome=MutationOutcome.PUBLISHED,
            operation=request.operation.value,
            protected_policy_version=request.protected_policy_version,
            canonical_target=relpath,
            before_kind=before.kind.value,
            before_ref=roots.ref_for(ArtifactKind.BEFORE),
            before_digest=digests[ArtifactKind.BEFORE],
            proposed_ref=roots.ref_for(ArtifactKind.PROPOSED),
            proposed_digest=proposed_digest,
            diff_ref=roots.ref_for(ArtifactKind.DIFF),
            diff_digest=digests[ArtifactKind.DIFF],
            target_digest=proposed_digest,
            journal_ref=roots.ref_for(ArtifactKind.JOURNAL),
            journal_status=JournalStatus.PUBLISHED.value,
        )

    def _conflict(
        self, request: MutationRequest, relpath: str, roots: ArtifactRoot, reason: str
    ) -> MutationResult:
        return MutationResult(
            outcome=MutationOutcome.CONFLICT,
            operation=request.operation.value,
            protected_policy_version=request.protected_policy_version,
            canonical_target=relpath,
            journal_ref=roots.ref_for(ArtifactKind.JOURNAL),
            journal_status=JournalStatus.PREPARED.value,
            permission_reason=reason,
        )

    def _fail(
        self,
        request: MutationRequest,
        outcome: MutationOutcome,
        *,
        canonical_target: str | None = None,
        permission_reason: str | None = None,
        validation_failures: tuple[str, ...] = (),
    ) -> MutationResult:
        return MutationResult(
            outcome=outcome,
            operation=request.operation.value,
            protected_policy_version=request.protected_policy_version,
            canonical_target=canonical_target,
            permission_reason=permission_reason,
            validation_failures=validation_failures,
        )
