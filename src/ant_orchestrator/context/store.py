"""Immutable context-package store + anti-TOCTOU verifier (PHASE_5_PLAN CP2).

Persists a prepared ``ContextPackage`` under the system-managed artifact root
(outside any worker write scope) with a stable, content-independent identity so the
same logical action reuses one package and a changed input fails closed as a
conflict. The verifier re-reads the persisted package and recomputes every digest so
a tampered, missing, or corrupt package fails closed before a worker consumes it.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ant_orchestrator.context.digest import (
    canonical_context_manifest,
    manifest_digest,
    normalize_source_path,
    source_digest,
)
from ant_orchestrator.context.package import ContextPackage
from ant_orchestrator.core.domain.errors import DomainError

_PACKAGE_ID_LENGTH: Final = 32
_MANIFEST_FILENAME: Final = "manifest.json"
_SOURCES_DIRNAME: Final = "sources"
_STAGING_PREFIX: Final = ".ctxpkg.tmp-"
_DIGEST_KEY: Final = "manifest_digest"
_CANONICAL_KEY: Final = "canonical"
_ARTIFACT_FILES_KEY: Final = "artifact_files"


class ContextStoreError(DomainError):
    """Base class for context-store integrity failures (fail-closed)."""


class ContextPackageMissing(ContextStoreError):
    """The referenced context package directory does not exist."""


class ContextArtifactCorrupt(ContextStoreError):
    """A persisted context artifact is unreadable or internally inconsistent."""


class ManifestDigestMismatch(ContextStoreError):
    """The persisted manifest digest does not match the expected digest."""


class SourceDigestMismatch(ContextStoreError):
    """A persisted source artifact's content no longer matches its digest."""


class ContextIdentityConflict(ContextStoreError):
    """A package already exists for this identity with a different digest."""


@dataclass(frozen=True, slots=True)
class PersistedContext:
    """Reference + digest a proposal binds to (both stable, JSON-safe strings)."""

    context_package_ref: str
    manifest_digest: str


class ContextPackageStore:
    """Persists and verifies immutable context packages under the artifact root.

    ``artifacts_root`` is the system-managed root (``<workspace>/.ant/artifacts``)
    resolved by the composition root; references are relative to it and may never
    escape it. The store imports no workspace layer — only the resolved path.
    """

    def __init__(self, artifacts_root: Path) -> None:
        self._root = artifacts_root

    def persist(
        self, run_id: str, logical_action_id: str, package: ContextPackage
    ) -> PersistedContext:
        """Persist immutably; reuse on identical digest, conflict on a changed one."""
        canonical = canonical_context_manifest(package)
        digest = manifest_digest(canonical)
        ref = self._ref(run_id, logical_action_id)
        target = self._resolve(ref)
        if target.exists():
            existing = self._read_manifest(target).get(_DIGEST_KEY)
            if existing == digest:
                return PersistedContext(ref, digest)
            raise ContextIdentityConflict(
                "context identity already persisted with a different digest"
            )
        self._write_package(target, canonical, digest, package)
        return PersistedContext(ref, digest)

    def verify(self, context_package_ref: str, expected_manifest_digest: str) -> None:
        """Fail closed unless the persisted package matches the expected digest exactly."""
        target = self._resolve(context_package_ref)
        if not target.is_dir():
            raise ContextPackageMissing("context package directory not found")
        document = self._read_manifest(target)
        canonical = document.get(_CANONICAL_KEY)
        stored_digest = document.get(_DIGEST_KEY)
        artifact_files = document.get(_ARTIFACT_FILES_KEY)
        if (
            not isinstance(canonical, dict)
            or not isinstance(stored_digest, str)
            or not isinstance(artifact_files, dict)
        ):
            raise ContextArtifactCorrupt("context manifest is structurally invalid")
        if manifest_digest(canonical) != stored_digest:
            raise ContextArtifactCorrupt("persisted manifest digest is inconsistent")
        if stored_digest != expected_manifest_digest:
            raise ManifestDigestMismatch("context manifest digest does not match proposal")
        self._verify_sources(target, canonical, artifact_files)

    # --- identity / paths ----------------------------------------------------
    @staticmethod
    def _encode(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:_PACKAGE_ID_LENGTH]

    def _ref(self, run_id: str, logical_action_id: str) -> str:
        enc_run = self._encode(run_id)
        package_id = self._encode(f"{run_id}\x00{logical_action_id}")
        return f"{enc_run}/context/{package_id}"

    def _resolve(self, ref: str) -> Path:
        target = (self._root / ref).resolve()
        artifacts = self._root.resolve()
        if target != artifacts and artifacts not in target.parents:
            raise ContextArtifactCorrupt("context reference escapes the artifact root")
        return target

    # --- persistence ---------------------------------------------------------
    def _write_package(
        self,
        target: Path,
        canonical: dict[str, object],
        digest: str,
        package: ContextPackage,
    ) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=_STAGING_PREFIX, dir=self._root))
        try:
            artifact_files = self._write_sources(staging, package)
            document = {
                "manifest_schema_version": canonical["manifest_schema_version"],
                _DIGEST_KEY: digest,
                _CANONICAL_KEY: canonical,
                _ARTIFACT_FILES_KEY: artifact_files,
            }
            (staging / _MANIFEST_FILENAME).write_text(
                json.dumps(document, ensure_ascii=False), encoding="utf-8"
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, target)
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    @staticmethod
    def _write_sources(staging: Path, package: ContextPackage) -> dict[str, str]:
        sources_dir = staging / _SOURCES_DIRNAME
        sources_dir.mkdir()
        artifact_files: dict[str, str] = {}
        for index, artifact in enumerate(package.artifacts):
            name = f"{_SOURCES_DIRNAME}/{index:04d}.txt"
            (staging / name).write_text(artifact.content, encoding="utf-8")
            artifact_files[normalize_source_path(artifact.path)] = name
        return artifact_files

    # --- verification --------------------------------------------------------
    def _read_manifest(self, target: Path) -> dict[str, object]:
        try:
            raw = (target / _MANIFEST_FILENAME).read_text(encoding="utf-8")
        except OSError:
            raise ContextPackageMissing("context manifest not found") from None
        try:
            document = json.loads(raw)
        except json.JSONDecodeError:
            raise ContextArtifactCorrupt("context manifest is not valid JSON") from None
        if not isinstance(document, dict):
            raise ContextArtifactCorrupt("context manifest is not an object")
        return document

    def _verify_sources(
        self, target: Path, canonical: dict[str, object], artifact_files: dict[str, object]
    ) -> None:
        sources = canonical.get("sources")
        if not isinstance(sources, list):
            raise ContextArtifactCorrupt("context manifest sources are invalid")
        for entry in sources:
            path = entry.get("path") if isinstance(entry, dict) else None
            expected = entry.get("content_digest") if isinstance(entry, dict) else None
            rel = artifact_files.get(path) if isinstance(path, str) else None
            if not isinstance(expected, str) or not isinstance(rel, str):
                raise ContextArtifactCorrupt("context source mapping is invalid")
            content = self._read_source(target, rel)
            if source_digest(content) != expected:
                raise SourceDigestMismatch("context source content no longer matches digest")

    @staticmethod
    def _read_source(target: Path, rel: str) -> str:
        file_path = (target / rel).resolve()
        if file_path != target.resolve() and target.resolve() not in file_path.parents:
            raise ContextArtifactCorrupt("context source escapes its package")
        try:
            return file_path.read_text(encoding="utf-8")
        except OSError:
            raise ContextArtifactCorrupt("context source artifact is missing") from None
