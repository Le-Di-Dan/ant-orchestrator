"""PHASE_5_PLAN CP6: pre-approval documentation preparation + approval binding."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextConsumer,
)
from ant_orchestrator.application.ports.document_worker import DocumentOperation
from ant_orchestrator.application.services.context_preparation import ContextPreparationService
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.integration.documentation_preparer import (
    DocumentationPreparer,
    DocumentationRequest,
)
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.workflows.graph import _bind_approval
from ant_orchestrator.workflows.nodes import PHASE_EXECUTE, PHASE_FAILED
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink
from tests.test_context_package import FakeFs

_TS = datetime(2026, 6, 27, tzinfo=UTC)
_SOURCE = "docs/source/brief.md"


def _artifacts(ws: Path) -> Path:
    return ws / ".ant" / "artifacts"


def _preparer(ws: Path) -> DocumentationPreparer:
    builder = ContextPackageBuilder(
        fs=FakeFs({_SOURCE: "brief body"}),
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=FakeAuditSink(),
        clock=FakeClock(UtcTimestamp(_TS)),
        id_gen=SequentialIdGenerator(),
    )
    store = ContextPackageStore(_artifacts(ws))
    service = ContextPreparationService(ContextSourcePreparerImpl(builder, store))
    return DocumentationPreparer(
        context_service=service,
        proposal_store=ProposalStore(_artifacts(ws)),
        consumer=ContextConsumer(ConsumerKind.WORKER, "documentation-ant"),
        budget=ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000),
    )


def _request() -> DocumentationRequest:
    return DocumentationRequest(
        logical_action_id="act-1",
        operation=DocumentOperation.CREATE,
        target_document="handoff",
        candidate_target="docs/handoffs/HANDOFF-001.md",
        instruction_summary="write a handoff",
        required_sections=("Summary",),
        approved_inputs=(_SOURCE,),
        canonical_read_scope=("docs/source",),
        canonical_write_scope=("docs/handoffs",),
        protected_policy_version=1,
        energy_estimate=10000,
    )


def test_prepare_builds_real_context_and_persists_proposal(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)
    prepared = preparer.prepare("run-1", _request())

    sf = prepared.state_fields
    assert sf["proposal_ref"] and sf["proposal_digest"]
    assert sf["context_package_ref"] and sf["manifest_digest"]
    assert "ctx:" not in str(sf["context_package_ref"])  # real package, not placeholder
    assert prepared.action_intent["requires_significant_write"] is True
    assert prepared.action_intent["logical_action_id"] == "act-1"

    # The persisted proposal is loadable and digest-verifies against the bound digest.
    loaded = ProposalStore(_artifacts(tmp_path)).load(
        str(sf["proposal_ref"]), str(sf["proposal_digest"])
    )
    assert loaded.proposal.manifest_digest == sf["manifest_digest"]
    assert loaded.task.logical_action_id == "act-1"


def test_prepare_initial_state_returns_none_without_factory(tmp_path: Path) -> None:
    preparer = _preparer(tmp_path)

    class _Task:
        pass

    assert preparer.prepare_initial_state("run-1", _Task()) is None  # type: ignore[arg-type]


def test_bind_approval_stamps_ref_on_matching_proposal() -> None:
    delta: dict[str, object] = {"phase": PHASE_EXECUTE}
    intent = {
        "gate_instance_id": "gate-abc",
        "sanitized_payload": {"proposal_digest": "pd-1"},
    }
    state = {"proposal_digest": "pd-1"}
    _bind_approval(delta, intent, state)  # type: ignore[arg-type]

    assert delta["phase"] == PHASE_EXECUTE
    assert delta["approval_ref"] == "gate-abc"


def test_bind_approval_fails_closed_on_mismatch() -> None:
    delta: dict[str, object] = {"phase": PHASE_EXECUTE}
    intent = {"gate_instance_id": "gate-abc", "sanitized_payload": {"proposal_digest": "other"}}
    state = {"proposal_digest": "pd-1"}
    _bind_approval(delta, intent, state)  # type: ignore[arg-type]

    assert delta["phase"] == PHASE_FAILED
    assert delta["error_summary"] == "approval_binding_mismatch"
    assert "approval_ref" not in delta


def test_bind_approval_noop_for_legacy_run_without_proposal() -> None:
    delta: dict[str, object] = {"phase": PHASE_EXECUTE}
    _bind_approval(delta, {"gate_instance_id": "g"}, {})  # type: ignore[arg-type]

    assert delta == {"phase": PHASE_EXECUTE}  # unchanged: no proposal binding
