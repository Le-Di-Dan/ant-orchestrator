"""Durable pre-approval proposal store (PHASE_5_PLAN CP6 §3).

The ``ExecutionProposal`` is built off-graph BEFORE human approval and persisted as a
system-managed JSON artifact (no DB migration). Its ``proposal_digest`` — recomputed on
load — is the authority the approval binds to, so a tampered proposal yields a different
digest and fails closed. The bundle also carries the semantic ``DocumentationTask`` (the
instruction the worker executes); the task grants no authority and is consistency-checked
against the proposal on load. Symlinks are rejected and the artifact is byte-bounded.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    DocumentOperation,
)
from ant_orchestrator.application.ports.execution_scope import ExecutionProposal
from ant_orchestrator.config.constants import MAX_ARTIFACT_BYTES
from ant_orchestrator.core.domain.value_objects import TokenCount
from ant_orchestrator.integration.errors import ProposalAuthorityError

_ENC_LEN: Final = 32
_FILENAME: Final = "proposal.json"


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    """A loaded, digest-verified proposal plus its semantic task."""

    proposal: ExecutionProposal
    task: DocumentationTask
    proposal_ref: str
    proposal_digest: str


class ProposalStore:
    """Persists/loads the immutable proposal bundle under the artifact root."""

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def persist(
        self,
        run_id: str,
        logical_action_id: str,
        proposal: ExecutionProposal,
        task: DocumentationTask,
    ) -> PreparedExecution:
        """Persist immutably; reuse on an identical digest, conflict on a changed one."""
        digest = proposal.proposal_digest()
        ref = self._ref(run_id, logical_action_id)
        path = self._resolve(ref)
        if path.exists():
            existing = self._read(path)
            if existing.proposal_digest() != digest:
                raise ProposalAuthorityError("proposal identity persisted with a different digest")
        else:
            self._write(path, proposal, task)
        return PreparedExecution(proposal, task, ref, digest)

    def load(self, proposal_ref: str, expected_digest: str) -> PreparedExecution:
        """Load + verify the proposal digest and task consistency; fail closed on mismatch."""
        path = self._resolve(proposal_ref)
        proposal, task = self._read_bundle(path)
        digest = proposal.proposal_digest()
        if digest != expected_digest:
            raise ProposalAuthorityError("proposal digest does not match the bound authority")
        if (
            task.logical_action_id != proposal.logical_action_id
            or task.operation is not proposal.operation
        ):
            raise ProposalAuthorityError("task is inconsistent with the bound proposal")
        return PreparedExecution(proposal, task, proposal_ref, digest)

    # --- pathing -----------------------------------------------------------
    @staticmethod
    def _encode(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_ENC_LEN]

    def _ref(self, run_id: str, logical_action_id: str) -> str:
        return f"{self._encode(run_id)}/proposal/{self._encode(logical_action_id)}/{_FILENAME}"

    def _resolve(self, ref: str) -> Path:
        target = (self._root / ref).resolve()
        root = self._root.resolve()
        if target != root and root not in target.parents:
            raise ProposalAuthorityError("proposal reference escapes the artifact root")
        return target

    # --- serialization -----------------------------------------------------
    def _write(self, path: Path, proposal: ExecutionProposal, task: DocumentationTask) -> None:
        if path.is_symlink():
            raise ProposalAuthorityError("refusing to write proposal through a symlink")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.dumps(
            {"proposal": _proposal_to_dict(proposal), "task": _task_to_dict(task)},
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        if len(data) > MAX_ARTIFACT_BYTES:
            raise ProposalAuthorityError("proposal artifact exceeds the size limit")
        tmp = path.parent / (path.name + ".tmp")
        with open(tmp, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)

    def _read(self, path: Path) -> ExecutionProposal:
        return self._read_bundle(path)[0]

    def _read_bundle(self, path: Path) -> tuple[ExecutionProposal, DocumentationTask]:
        if path.is_symlink():
            raise ProposalAuthorityError("refusing to read proposal through a symlink")
        try:
            raw = path.read_bytes()
        except OSError:
            raise ProposalAuthorityError("proposal artifact is missing") from None
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise ProposalAuthorityError("proposal artifact exceeds the size limit")
        try:
            document = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ProposalAuthorityError("proposal artifact is not valid JSON") from None
        if not isinstance(document, dict):
            raise ProposalAuthorityError("proposal artifact is not an object")
        try:
            return _proposal_from_dict(document["proposal"]), _task_from_dict(document["task"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ProposalAuthorityError("proposal artifact is structurally invalid") from exc


def _proposal_to_dict(proposal: ExecutionProposal) -> dict[str, object]:
    return {
        "run_id": proposal.run_id,
        "logical_action_id": proposal.logical_action_id,
        "task_ref": proposal.task_ref,
        "candidate_target": proposal.candidate_target,
        "operation": proposal.operation.value,
        "canonical_read_scope": list(proposal.canonical_read_scope),
        "canonical_write_scope": list(proposal.canonical_write_scope),
        "protected_policy_version": proposal.protected_policy_version,
        "context_package_ref": proposal.context_package_ref,
        "manifest_digest": proposal.manifest_digest,
        "energy_estimate": proposal.energy_estimate.value,
        "expected_mutation": proposal.expected_mutation,
        "proposal_version": proposal.proposal_version,
        "proposal_key": proposal.proposal_key,
    }


def _str(data: dict[str, object], key: str) -> str:
    return str(data[key])


def _int(data: dict[str, object], key: str) -> int:
    value = data[key]
    if not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _str_tuple(data: dict[str, object], key: str) -> tuple[str, ...]:
    value = data[key]
    if not isinstance(value, list):
        raise ValueError(f"{key} must be a list")
    return tuple(str(item) for item in value)


def _proposal_from_dict(data: dict[str, object]) -> ExecutionProposal:
    return ExecutionProposal(
        run_id=_str(data, "run_id"),
        logical_action_id=_str(data, "logical_action_id"),
        task_ref=_str(data, "task_ref"),
        candidate_target=_str(data, "candidate_target"),
        operation=DocumentOperation(_str(data, "operation")),
        canonical_read_scope=_str_tuple(data, "canonical_read_scope"),
        canonical_write_scope=_str_tuple(data, "canonical_write_scope"),
        protected_policy_version=_int(data, "protected_policy_version"),
        context_package_ref=_str(data, "context_package_ref"),
        manifest_digest=_str(data, "manifest_digest"),
        energy_estimate=TokenCount(_int(data, "energy_estimate")),
        expected_mutation=_str(data, "expected_mutation"),
        proposal_version=_int(data, "proposal_version"),
        proposal_key=_str(data, "proposal_key"),
    )


def _task_to_dict(task: DocumentationTask) -> dict[str, object]:
    return {
        "logical_action_id": task.logical_action_id,
        "operation": task.operation.value,
        "target_document": task.target_document,
        "instruction_summary": task.instruction_summary,
        "required_sections": list(task.required_sections),
        "approved_inputs": list(task.approved_inputs),
        "expected_document_purpose": task.expected_document_purpose,
    }


def _task_from_dict(data: dict[str, object]) -> DocumentationTask:
    return DocumentationTask(
        logical_action_id=_str(data, "logical_action_id"),
        operation=DocumentOperation(_str(data, "operation")),
        target_document=_str(data, "target_document"),
        instruction_summary=_str(data, "instruction_summary"),
        required_sections=_str_tuple(data, "required_sections"),
        approved_inputs=_str_tuple(data, "approved_inputs"),
        expected_document_purpose=str(data.get("expected_document_purpose", "")),
    )
