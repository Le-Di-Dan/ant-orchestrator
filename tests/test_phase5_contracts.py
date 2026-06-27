"""CP1 contract tests — Phase 5 typed data layers and authority separation.

Proves the four data layers are distinct and that authority is NOT carried by the
semantic task or the model draft:
- ``DocumentationTask`` carries no permission/scope/attempt authority (I4).
- ``ModelCompositionDraft`` carries no operational-fact fields (I2).
- ``ExecutionProposal`` carries no approval/attempt fields (I12).
- ``ApprovedExecutionScope`` is immutable and requires approval+attempt (I12).
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, fields

import pytest

from ant_orchestrator.application.ports.document_worker import (
    MAX_PROPOSED_CONTENT_CHARS,
    DocumentationTask,
    DocumentOperation,
    ModelCompositionDraft,
    WorkerExecutionReport,
)
from ant_orchestrator.application.ports.execution_scope import (
    ApprovedExecutionScope,
    ExecutionProposal,
)
from ant_orchestrator.application.ports.worker import WorkerOutcome
from ant_orchestrator.core.domain.errors import InvariantViolation
from ant_orchestrator.core.domain.value_objects import TokenCount

# Fields that would smuggle authority/operational facts into the wrong layer.
_AUTHORITY_FIELDS = frozenset(
    {
        "target_path",
        "approved_target",
        "candidate_target",
        "allowed_write_paths",
        "allowed_read_paths",
        "canonical_read_scope",
        "canonical_write_scope",
        "scope",
        "approval_ref",
        "attempt_id",
        "execution_attempt_id",
        "permission",
    }
)
_OPERATIONAL_FACT_FIELDS = frozenset(
    {
        "files_read",
        "files_changed",
        "commands",
        "diff",
        "evidence_refs",
        "result",
        "permission",
        "target_path",
        "scope",
    }
)


def _field_names(cls: type) -> set[str]:
    return {f.name for f in fields(cls)}


def _task() -> DocumentationTask:
    return DocumentationTask(
        logical_action_id="act-1",
        operation=DocumentOperation.CREATE,
        target_document="task handoff",
        instruction_summary="write a handoff",
        required_sections=("Summary", "What Changed", "Next Steps"),
        approved_inputs=("docs/source/task_brief.md",),
        expected_document_purpose="record task handoff",
    )


def _proposal() -> ExecutionProposal:
    return ExecutionProposal(
        run_id="run-1",
        logical_action_id="act-1",
        task_ref="task-1",
        candidate_target="docs/handoffs/HANDOFF-001.md",
        operation=DocumentOperation.CREATE,
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        protected_policy_version=1,
        context_package_ref="ctxpkg-1",
        manifest_digest="m" * 64,
        energy_estimate=TokenCount(1000),
        expected_mutation="create docs/handoffs/HANDOFF-001.md",
        proposal_version=1,
        proposal_key="prop-key-1",
    )


def _scope() -> ApprovedExecutionScope:
    return ApprovedExecutionScope(
        attempt_id="attempt-1",
        approval_ref="approval-1",
        proposal_ref="prop-key-1",
        proposal_digest="d" * 64,
        approved_target="docs/handoffs/HANDOFF-001.md",
        approved_operation=DocumentOperation.CREATE,
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        context_package_ref="ctxpkg-1",
        manifest_digest="m" * 64,
        protected_policy_version=1,
        energy_reservation_ref="resv-1",
        artifact_root=".ant/artifacts/run-1/attempt-1",
        idempotency_key="run-1/act-1/dddd/attempt-1",
    )


# --- DocumentationTask: semantic only --------------------------------------


def test_documentation_task_carries_no_authority_fields() -> None:
    assert _field_names(DocumentationTask).isdisjoint(_AUTHORITY_FIELDS)


def test_documentation_task_invariants() -> None:
    assert _task().operation is DocumentOperation.CREATE
    with pytest.raises(InvariantViolation):
        DocumentationTask(
            logical_action_id="",
            operation=DocumentOperation.CREATE,
            target_document="x",
            instruction_summary="y",
            required_sections=("S",),
        )
    with pytest.raises(InvariantViolation):
        DocumentationTask(
            logical_action_id="a",
            operation=DocumentOperation.CREATE,
            target_document="",
            instruction_summary="y",
            required_sections=("S",),
        )
    with pytest.raises(InvariantViolation):
        DocumentationTask(
            logical_action_id="a",
            operation=DocumentOperation.CREATE,
            target_document="x",
            instruction_summary="y",
            required_sections=("",),
        )


# --- ModelCompositionDraft: not authoritative ------------------------------


def test_model_draft_has_no_operational_fact_fields() -> None:
    assert _field_names(ModelCompositionDraft).isdisjoint(_OPERATIONAL_FACT_FIELDS)
    assert _field_names(ModelCompositionDraft) == {
        "proposed_content",
        "summary",
        "risks",
        "next_steps",
    }


def test_model_draft_bounds() -> None:
    ModelCompositionDraft(proposed_content="ok")
    with pytest.raises(InvariantViolation):
        ModelCompositionDraft(proposed_content="x" * (MAX_PROPOSED_CONTENT_CHARS + 1))


# --- WorkerExecutionReport: §12 system-assembled ---------------------------


def test_report_models_all_section_12_fields() -> None:
    report = WorkerExecutionReport(
        summary="done",
        files_read=("docs/source/task_brief.md",),
        files_changed=("docs/handoffs/HANDOFF-001.md",),
        commands=(),
        result=WorkerOutcome.SUCCESS,
        evidence_refs=("ev-1",),
        risks=("none",),
        next_steps=("review",),
    )
    assert report.result is WorkerOutcome.SUCCESS
    required = {
        "summary",
        "files_read",
        "files_changed",
        "commands",
        "result",
        "evidence_refs",
        "risks",
        "next_steps",
    }
    assert required.issubset(_field_names(WorkerExecutionReport))


# --- ExecutionProposal: no approval/attempt (I12) + digest -----------------


def test_proposal_has_no_approval_or_attempt_fields() -> None:
    names = _field_names(ExecutionProposal)
    assert "approval_ref" not in names
    assert "attempt_id" not in names
    assert "execution_attempt_id" not in names


def test_proposal_digest_is_deterministic_and_content_sensitive() -> None:
    assert _proposal().proposal_digest() == _proposal().proposal_digest()
    from dataclasses import replace

    other = replace(_proposal(), candidate_target="docs/handoffs/OTHER.md")
    assert other.proposal_digest() != _proposal().proposal_digest()


def test_proposal_invariants() -> None:
    from dataclasses import replace

    with pytest.raises(InvariantViolation):
        replace(_proposal(), candidate_target="")
    with pytest.raises(InvariantViolation):
        replace(_proposal(), protected_policy_version=0)


# --- ApprovedExecutionScope: immutable + requires approval+attempt ---------


def test_scope_is_immutable() -> None:
    scope = _scope()
    with pytest.raises(FrozenInstanceError):
        scope.approved_target = "docs/other.md"  # type: ignore[misc]


def test_scope_requires_attempt_and_approval() -> None:
    from dataclasses import replace

    with pytest.raises(InvariantViolation):
        replace(_scope(), attempt_id="")
    with pytest.raises(InvariantViolation):
        replace(_scope(), approval_ref="")
    with pytest.raises(InvariantViolation):
        replace(_scope(), artifact_root="")
