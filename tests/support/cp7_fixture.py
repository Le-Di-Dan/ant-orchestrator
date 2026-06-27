"""CP7 fixture harness: a full production workflow stack over a temp workspace.

Builds the real Phase 5 vertical slice — bootstrapped Nest + SQLite, real bounded
filesystem + context builder, durable energy, proposal/approval binding, the durable
execution adapter, and the LangGraph runner — wired through ``build_workflow_services``
with a deterministic (or live) composer. Tests drive ``create_task`` → ``run_workflow``
→ ``resolve_approval`` exactly as the CLI would, then assert the durable evidence bundle.
No fixture *source* is mutated: every run operates on a copied temporary Nest.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from ant_orchestrator.application.ports.context_builder import (
    ConsumerKind,
    ContextBudget,
    ContextConsumer,
)
from ant_orchestrator.application.ports.document_worker import (
    DocumentationTask,
    DocumentOperation,
)
from ant_orchestrator.application.ports.documentation_composer import (
    ComposerContext,
    CompositionConstraints,
    CompositionResult,
)
from ant_orchestrator.application.ports.llm import ModelUsage
from ant_orchestrator.application.services.context_preparation import ContextPreparationService
from ant_orchestrator.cli.workflow_composition import WorkflowServices, build_workflow_services
from ant_orchestrator.config.constants import DOC_PROMPT_TEMPLATE_ID
from ant_orchestrator.context.estimator import CharacterHeuristicEstimator
from ant_orchestrator.context.package import ContextPackageBuilder
from ant_orchestrator.context.preparation import ContextSourcePreparerImpl
from ant_orchestrator.context.selection import ContextSelector
from ant_orchestrator.context.store import ContextPackageStore
from ant_orchestrator.core.domain.entities import Task
from ant_orchestrator.core.domain.value_objects import UtcTimestamp
from ant_orchestrator.execution.bounded_fs import BoundedFileSystemAdapter, BoundedFsConfig
from ant_orchestrator.integration.composition import build_documentation_execution
from ant_orchestrator.integration.documentation_preparer import (
    DocumentationPreparer,
    DocumentationRequest,
)
from ant_orchestrator.integration.proposal_store import ProposalStore
from ant_orchestrator.persistence.database import Database
from ant_orchestrator.persistence.migrations import SqliteDatabaseBootstrapper
from ant_orchestrator.persistence.unit_of_work import SqliteUnitOfWork
from ant_orchestrator.security.path_policy import PathPolicy, PathScope
from ant_orchestrator.security.protected_path_policy import ProtectedPathPolicy
from ant_orchestrator.security.redaction.redactor import Redactor
from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME
from tests.conftest import FakeClock, SequentialIdGenerator
from tests.support.fake_audit_sink import FakeAuditSink

_TS = UtcTimestamp(datetime(2026, 6, 27, tzinfo=UTC))
_CONSUMER = ContextConsumer(ConsumerKind.WORKER, "documentation-ant")
_BUDGET = ContextBudget(max_input_tokens=10000, max_files=10, max_file_tokens=5000)

HANDOFF_DIR = "docs/handoffs"
BRIEF = "docs/source/brief.md"
CREATE_TARGET = "docs/handoffs/HANDOFF-001.md"
SECTIONS = ("Summary", "What Changed", "Next Steps")


class RecordingComposer:
    """Deterministic composer that records calls and returns a fixed sectioned draft."""

    def __init__(self, *, sections: tuple[str, ...] = SECTIONS, body: str = "fixture body") -> None:
        self.calls = 0
        self._content = "\n\n".join(f"## {s}\n\n{body}" for s in sections)

    async def compose(
        self, task: DocumentationTask, context: ComposerContext, constraints: CompositionConstraints
    ) -> CompositionResult:
        self.calls += 1
        from ant_orchestrator.application.ports.document_worker import ModelCompositionDraft

        return CompositionResult(
            draft=ModelCompositionDraft(
                proposed_content=self._content, summary="fixture summary", next_steps=("ship",)
            ),
            usage=ModelUsage.measured(tokens_in=12, tokens_out=20),
            provider_id="fake",
            model_id="fake-model",
            prompt_template_id=DOC_PROMPT_TEMPLATE_ID,
            prompt_template_version=1,
        )


def write_fixture(workspace_root: Path, *, brief: str = "Write a handoff.") -> None:
    """Materialise the read-only fixture inputs into a fresh temporary Nest."""
    (workspace_root / ANT_DIRNAME).mkdir(parents=True, exist_ok=True)
    src = workspace_root / "docs" / "source"
    src.mkdir(parents=True, exist_ok=True)
    (src / "brief.md").write_text(brief, encoding="utf-8")
    (workspace_root / HANDOFF_DIR).mkdir(parents=True, exist_ok=True)


def create_request(
    *, operation: DocumentOperation = DocumentOperation.CREATE, target: str = CREATE_TARGET
) -> DocumentationRequest:
    return DocumentationRequest(
        logical_action_id="doc-act",
        operation=operation,
        target_document="handoff",
        candidate_target=target,
        instruction_summary="write a handoff document",
        required_sections=SECTIONS,
        approved_inputs=(BRIEF,),
        canonical_read_scope=("docs/source",),
        canonical_write_scope=(HANDOFF_DIR,),
        protected_policy_version=1,
        energy_estimate=10000,
        expected_mutation=operation.value,
    )


def build_services(
    workspace_root: Path,
    *,
    composer: object,
    request_factory: Callable[[Task], DocumentationRequest | None] | None = None,
) -> WorkflowServices:
    """Assemble the full production workflow services over ``workspace_root``."""
    clock = FakeClock(_TS)
    ids = SequentialIdGenerator(prefix="CP7")
    ant_dir = workspace_root / ANT_DIRNAME
    db_path = ant_dir / DATABASE_FILENAME
    SqliteDatabaseBootstrapper(clock).bootstrap(db_path)
    artifacts_root = ant_dir / "artifacts"
    handoffs = workspace_root / HANDOFF_DIR

    database = Database(db_path)

    def uow_factory() -> SqliteUnitOfWork:
        return SqliteUnitOfWork(database)

    audit = FakeAuditSink()
    fs = BoundedFileSystemAdapter(
        config=BoundedFsConfig(workspace_root=workspace_root),
        path_policy=PathPolicy(
            PathScope.build(read_roots=(workspace_root,), write_roots=(handoffs,)),
            workspace_root=workspace_root,
        ),
        redactor=Redactor(),
        audit_sink=audit,
        clock=clock,
        id_gen=ids,
    )
    builder = ContextPackageBuilder(
        fs=fs,
        estimator=CharacterHeuristicEstimator(divisor=4),
        selector=ContextSelector(),
        audit_sink=audit,
        clock=clock,
        id_gen=ids,
    )
    context_service = ContextPreparationService(
        ContextSourcePreparerImpl(builder, ContextPackageStore(artifacts_root))
    )
    policy = ProtectedPathPolicy(
        scope=PathScope.build(read_roots=(), write_roots=(handoffs,)),
        workspace_root=workspace_root,
        policy_version=1,
    )
    adapter = build_documentation_execution(
        composer=composer,  # type: ignore[arg-type]
        policy=policy,
        uow_factory=uow_factory,
        clock=clock,
        ids=ids,
        workspace_root=workspace_root,
        artifacts_root=artifacts_root,
    )
    factory = request_factory if request_factory is not None else (lambda _task: create_request())
    preparer = DocumentationPreparer(
        context_service=context_service,
        proposal_store=ProposalStore(artifacts_root),
        consumer=_CONSUMER,
        budget=_BUDGET,
        request_factory=factory,
    )
    return build_workflow_services(
        workspace_root, documentation_execution=adapter, documentation_preparer=preparer
    )
