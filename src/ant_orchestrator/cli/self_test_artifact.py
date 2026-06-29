"""Deterministic internal artifact for the self-test (Phase 8 CP7 carry-forward B).

The self-test composition wires :class:`SelfTestArtifactProvider` into the
TaskResultFinalizer so the deterministic scenario exercises the *real* artifact
pipeline: a fixed harmless file is written under the temporary Nest's
``.ant/artifacts/self-test/`` directory, an :class:`ArtifactRef` with its true
SHA-256/size is persisted alongside the TaskResult, and the self-test then verifies
digest, path safety, retrieval and cleanup. No provider output is involved.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from ant_orchestrator.core.domain.task_result import (
    ArtifactKind,
    ArtifactRef,
    ArtifactState,
)

# Fixed, machine-independent payload — never derived from provider/model output.
SELF_TEST_ARTIFACT_CONTENT: Final = "Ant-Orchestrator deterministic self-test artifact"
SELF_TEST_ARTIFACT_MEDIA_TYPE: Final = "text/plain; charset=utf-8"
# Stored relative to the artifacts root (``.ant/artifacts``); forward slashes only.
SELF_TEST_ARTIFACT_SUBDIR: Final = "self-test"
SELF_TEST_ARTIFACT_FILENAME: Final = "self-test-artifact.txt"
SELF_TEST_ARTIFACT_RELATIVE_PATH: Final = (
    f"{SELF_TEST_ARTIFACT_SUBDIR}/{SELF_TEST_ARTIFACT_FILENAME}"
)


class SelfTestArtifactProvider:
    """Writes one deterministic internal artifact and returns its ``ArtifactRef``.

    Bound to the self-test ``artifacts_root`` (inside the temporary workspace). The
    finalizer only calls :meth:`provide` on the create path, so a replay/re-run never
    rewrites the file or persists a duplicate ref.
    """

    def __init__(self, artifacts_root: Path) -> None:
        self._artifacts_root = artifacts_root

    def provide(
        self, *, run_id: str, task_id: str, state: Mapping[str, object]
    ) -> tuple[ArtifactRef, ...]:
        content_bytes = SELF_TEST_ARTIFACT_CONTENT.encode("utf-8")
        target = self._artifacts_root / SELF_TEST_ARTIFACT_SUBDIR / SELF_TEST_ARTIFACT_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content_bytes)

        ref = ArtifactRef(
            artifact_id=f"selftest-artifact-{run_id}",
            kind=ArtifactKind.INTERNAL,
            relative_path=SELF_TEST_ARTIFACT_RELATIVE_PATH,
            media_type=SELF_TEST_ARTIFACT_MEDIA_TYPE,
            sha256=hashlib.sha256(content_bytes).hexdigest(),
            size_bytes=len(content_bytes),
            created_by_attempt_id=None,
            state=ArtifactState.FINAL,
            metadata="{}",
        )
        return (ref,)
