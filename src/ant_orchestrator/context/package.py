"""Context package builder — immutable consumer-scoped context and manifest (CP6).

Orchestrates the full pipeline: request validation, secret filename rejection,
scope-checked reads via ``FileSystemAdapter`` port, redaction tracing, token
estimation, deterministic selection, manifest construction, and audit. Never
scans the repository, never imports concrete adapters, never calls subprocess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from ant_orchestrator.application.ports.audit import (
    AuditEvent,
    AuditEventType,
    AuditSink,
    CorrelationId,
)
from ant_orchestrator.application.ports.context_builder import (
    ArtifactRequest,
    ArtifactRequirement,
    ContextBudget,
    ContextBuildRequest,
    ContextConsumer,
    ContextError,
    MemoryContextSelection,
)
from ant_orchestrator.application.ports.filesystem import (
    ContentRedaction,
    FileFailureCode,
    FileReadRequest,
    FileReadResult,
    FileSystemAdapter,
)
from ant_orchestrator.application.ports.memory_context import MemoryContextEntry
from ant_orchestrator.application.ports.tool_errors import (
    ToolAdapterError,
    ToolInvalidRequestError,
    ToolNotFoundError,
    ToolPermissionError,
)
from ant_orchestrator.context.budget import BudgetUsage
from ant_orchestrator.context.estimator import TokenEstimator
from ant_orchestrator.context.memory import (
    MemoryContextSection,
    MemoryRecordManifest,
)
from ant_orchestrator.context.selection import (
    ArtifactCandidate,
    ContextSelectionResult,
    ContextSelector,
    RejectionReason,
    SelectedArtifact,
)
from ant_orchestrator.core.domain.enums import PolicyDecision
from ant_orchestrator.core.domain.value_objects import TokenCount, UtcTimestamp
from ant_orchestrator.core.ports.clock import Clock
from ant_orchestrator.core.ports.ids import IdGenerator

_SECRET_FILE_RE: Final = re.compile(
    r"(?i)(?:^|[/\\])\.env(?:\..+)?$"
    r"|(?:^|[/\\])(?:credentials|secrets?|private[_-]?key)(?:\.\w+)?$"
    r"|\.pem$|\.key$|id_rsa$|id_ed25519$|id_ecdsa$"
)
_CONTEXT_POLICY_VERSION: Final = 1


def is_secret_filename(path: str) -> bool:
    return _SECRET_FILE_RE.search(path) is not None


@dataclass(frozen=True, slots=True)
class ContextArtifact:
    """A file artifact included in the context package."""

    path: str
    content: str
    estimated_tokens: TokenCount
    redactions: tuple[ContentRedaction, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class ManifestRejection:
    """A rejected artifact with typed reason and requirement context."""

    path: str
    reason: RejectionReason
    requirement: ArtifactRequirement


@dataclass(frozen=True, slots=True)
class ContextManifest:
    """Immutable manifest describing a context build outcome."""

    task_id: str
    consumer: ContextConsumer
    selected: tuple[SelectedArtifact, ...]
    rejected: tuple[ManifestRejection, ...]
    budget_initial: ContextBudget
    budget_used: BudgetUsage
    budget_remaining: BudgetUsage
    redactions_applied: tuple[ContentRedaction, ...]
    any_truncated: bool
    estimator_strategy: str
    estimator_version: int
    policy_version: int
    created_at: UtcTimestamp
    dispatchable: bool
    memory_section: MemoryContextSection | None = None


@dataclass(frozen=True, slots=True)
class ContextPackage:
    """Immutable context package: manifest + artifacts + memory entries."""

    manifest: ContextManifest
    artifacts: tuple[ContextArtifact, ...]
    memory_entries: tuple[MemoryContextEntry, ...] = ()


class ContextBuildFailure(ContextError):
    """An infrastructure failure prevented the context build from completing."""


class ContextPackageBuilder:
    """Builds context packages from explicit requests — no repository scanning."""

    def __init__(
        self,
        fs: FileSystemAdapter,
        estimator: TokenEstimator,
        selector: ContextSelector,
        audit_sink: AuditSink,
        clock: Clock,
        id_gen: IdGenerator,
    ) -> None:
        self._fs = fs
        self._est = estimator
        self._sel = selector
        self._audit = audit_sink
        self._clock = clock
        self._ids = id_gen

    async def build(self, request: ContextBuildRequest) -> ContextPackage:
        cid = CorrelationId(self._ids.new_id())
        deduped = _deduplicate_requests(request.requests)
        excluded = frozenset(request.excluded)
        candidates: list[ArtifactCandidate] = []
        read_cache: dict[str, FileReadResult] = {}
        req_map: dict[str, ArtifactRequirement] = {}

        for order, art_req in enumerate(deduped):
            req_map[art_req.path] = art_req.requirement
            if art_req.path in excluded:
                candidates.append(_ineligible(art_req, RejectionReason.EXCLUDED, order))
                continue
            if is_secret_filename(art_req.path):
                candidates.append(_ineligible(art_req, RejectionReason.SECRET_FILE, order))
                continue
            cand = await self._resolve_candidate(art_req, order, read_cache)
            candidates.append(cand)

        sel_result = self._sel.select(tuple(candidates), excluded, request.budget)
        artifacts = _build_artifacts(sel_result, read_cache)
        manifest = _build_manifest(
            request,
            sel_result,
            artifacts,
            req_map,
            self._est,
            self._clock,
        )
        mem_entries = (
            request.memory_selection.entries if request.memory_selection is not None else ()
        )
        pkg = ContextPackage(manifest=manifest, artifacts=artifacts, memory_entries=mem_entries)
        self._audit_build(cid, manifest)
        return pkg

    async def _resolve_candidate(
        self,
        art_req: ArtifactRequest,
        order: int,
        cache: dict[str, FileReadResult],
    ) -> ArtifactCandidate:
        try:
            result = await self._fs.read_text(FileReadRequest(path=art_req.path))
        except ToolPermissionError:
            return _ineligible(art_req, RejectionReason.OUTSIDE_SCOPE, order)
        except ToolNotFoundError:
            return _ineligible(art_req, RejectionReason.OUTSIDE_SCOPE, order)
        except ToolInvalidRequestError as exc:
            reason = _map_detail(exc.detail_code)
            return _ineligible(art_req, reason, order)
        except ToolAdapterError:
            raise ContextBuildFailure("infrastructure read failure") from None

        cache[art_req.path] = result
        tokens = self._est.estimate(result.content)
        return ArtifactCandidate(
            request=art_req,
            estimated_tokens=tokens,
            eligible=True,
            rejection_reason=None,
            original_order=order,
        )

    def _audit_build(self, cid: CorrelationId, m: ContextManifest) -> None:
        agg_redactions = sum(r.count for r in m.redactions_applied)
        self._audit.write(
            AuditEvent(
                event_type=AuditEventType.CONTEXT_BUILD,
                correlation_id=cid,
                created_at=m.created_at,
                detail={
                    "task_id": m.task_id,
                    "consumer_kind": m.consumer.kind.value,
                    "selected_count": str(len(m.selected)),
                    "rejected_count": str(len(m.rejected)),
                    "tokens_used": str(m.budget_used.tokens),
                    "tokens_remaining": str(m.budget_remaining.tokens),
                    "redactions": str(agg_redactions),
                    "dispatchable": str(m.dispatchable),
                },
                decision=PolicyDecision.ALLOW if m.dispatchable else PolicyDecision.DENY,
            )
        )


def _deduplicate_requests(
    requests: tuple[ArtifactRequest, ...],
) -> list[ArtifactRequest]:
    seen: dict[str, ArtifactRequest] = {}
    for r in requests:
        if r.path not in seen:
            seen[r.path] = r
        elif (
            r.requirement is ArtifactRequirement.REQUIRED
            and seen[r.path].requirement is ArtifactRequirement.OPTIONAL
        ):
            seen[r.path] = r
    return list(seen.values())


def _ineligible(
    req: ArtifactRequest,
    reason: RejectionReason,
    order: int,
) -> ArtifactCandidate:
    return ArtifactCandidate(
        request=req,
        estimated_tokens=TokenCount(0),
        eligible=False,
        rejection_reason=reason,
        original_order=order,
    )


def _map_detail(detail_code: str | None) -> RejectionReason:
    if detail_code == FileFailureCode.BINARY_CONTENT.value:
        return RejectionReason.BINARY
    if detail_code == FileFailureCode.OVERSIZED.value:
        return RejectionReason.OVERSIZED
    return RejectionReason.INVALID_REQUEST


def _build_artifacts(
    sel: ContextSelectionResult,
    cache: dict[str, FileReadResult],
) -> tuple[ContextArtifact, ...]:
    arts: list[ContextArtifact] = []
    for s in sel.selected:
        rr = cache[s.path]
        arts.append(
            ContextArtifact(
                path=s.path,
                content=rr.content,
                estimated_tokens=s.estimated_tokens,
                redactions=rr.redactions,
                truncated=False,
            )
        )
    return tuple(arts)


def _build_manifest(
    request: ContextBuildRequest,
    sel: ContextSelectionResult,
    artifacts: tuple[ContextArtifact, ...],
    req_map: dict[str, ArtifactRequirement],
    estimator: TokenEstimator,
    clock: Clock,
) -> ContextManifest:
    all_redactions: list[ContentRedaction] = []
    for a in artifacts:
        all_redactions.extend(a.redactions)
    rejections = tuple(
        ManifestRejection(
            path=r.path,
            reason=r.reason,
            requirement=req_map.get(r.path, ArtifactRequirement.OPTIONAL),
        )
        for r in sel.rejected
    )
    memory_section = _build_memory_section(request.memory_selection)
    return ContextManifest(
        task_id=str(request.task_id),
        consumer=request.consumer,
        selected=sel.selected,
        rejected=rejections,
        budget_initial=request.budget,
        budget_used=sel.budget_used,
        budget_remaining=sel.budget_remaining,
        redactions_applied=tuple(all_redactions),
        any_truncated=any(a.truncated for a in artifacts),
        estimator_strategy=estimator.strategy.value,
        estimator_version=estimator.version,
        policy_version=_CONTEXT_POLICY_VERSION,
        created_at=clock.now(),
        dispatchable=not sel.required_failure,
        memory_section=memory_section,
    )


def _build_memory_section(
    sel: MemoryContextSelection | None,
) -> MemoryContextSection | None:
    if sel is None or not sel.entries:
        return None
    records = tuple(
        MemoryRecordManifest(record_id=e.record_id, memory_type=e.type_value) for e in sel.entries
    )
    return MemoryContextSection(
        applied_filter=sel.applied_filter,
        records=records,
        returned_count=len(records),
        budget_consumed_tokens=sel.consumed_tokens,
    )
