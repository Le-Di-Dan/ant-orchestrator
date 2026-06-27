"""Canonical context-manifest representation and SHA-256 digests (PHASE_5_PLAN CP2).

Digests bind an ``ExecutionProposal`` to the exact context a worker may consume.
The canonical representation is deterministic (sorted keys, sources sorted by path)
and excludes runtime-variable fields (timestamps, absolute temporary paths) so the
same logical context yields the same digest across processes and workspaces. Only
already-redacted content is hashed — never a raw secret.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from ant_orchestrator.context.package import ContextPackage

DIGEST_ALGORITHM: Final = "sha256"
CONTEXT_MANIFEST_SCHEMA_VERSION: Final = 1
_CANONICAL_SEPARATORS: Final = (",", ":")


def normalize_source_path(path: str) -> str:
    """Workspace-relative, forward-slash form (never an absolute temporary path)."""
    return path.replace("\\", "/")


def _sha256_hex(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def source_digest(content: str) -> str:
    """SHA-256 of a single (already-redacted) source artifact's content."""
    return _sha256_hex(content)


def canonical_context_manifest(package: ContextPackage) -> dict[str, object]:
    """Build the deterministic, identity-bearing manifest representation.

    Excludes ``created_at`` and any absolute path so the digest is stable across
    runs and temporary workspaces. Sources are sorted by normalized path so map/set
    ordering can never change the digest.
    """
    manifest = package.manifest
    sources: list[dict[str, object]] = [
        {
            "path": normalize_source_path(artifact.path),
            "content_digest": source_digest(artifact.content),
            "estimated_tokens": artifact.estimated_tokens.value,
        }
        for artifact in package.artifacts
    ]
    sources.sort(key=lambda entry: str(entry["path"]))
    return {
        "manifest_schema_version": CONTEXT_MANIFEST_SCHEMA_VERSION,
        "task_id": manifest.task_id,
        "consumer_kind": manifest.consumer.kind.value,
        "consumer_value": manifest.consumer.value,
        "policy_version": manifest.policy_version,
        "estimator_strategy": manifest.estimator_strategy,
        "estimator_version": manifest.estimator_version,
        "sources": sources,
    }


def canonical_json(payload: dict[str, object]) -> str:
    """Canonical JSON encoding used for every context digest (stable ordering)."""
    return json.dumps(payload, sort_keys=True, separators=_CANONICAL_SEPARATORS, ensure_ascii=False)


def manifest_digest(canonical: dict[str, object]) -> str:
    """SHA-256 over the canonical manifest representation."""
    return _sha256_hex(canonical_json(canonical))
