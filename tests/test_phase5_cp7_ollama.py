"""PHASE_5_PLAN CP7: provider-backed (live Ollama) documentation slice — NON-DEFAULT.

Explicitly gated behind ``ANT_OLLAMA_E2E=1`` so it never runs in the default quality gate
(which uses the deterministic fake composer). It drives the SAME production vertical slice
through the real LiteLLM/Ollama seam against a local model, then verifies the durable
evidence bundle and that no raw provider output leaks into the persisted evidence.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from ant_orchestrator.workspace.layout import ANT_DIRNAME, DATABASE_FILENAME
from tests.support.cp7_fixture import CREATE_TARGET, SECTIONS, build_services, write_fixture

_MODEL = os.environ.get("ANT_OLLAMA_MODEL", "qwen2.5-coder:7b")
_BASE_URL = os.environ.get("ANT_OLLAMA_BASE_URL", "http://localhost:11434")

pytestmark = pytest.mark.skipif(
    os.environ.get("ANT_OLLAMA_E2E") != "1",
    reason="live Ollama slice is non-default; set ANT_OLLAMA_E2E=1 to run",
)


def _live_composer() -> object:
    from ant_orchestrator.adapters.litellm_client import LiteLLMSdkClient
    from ant_orchestrator.adapters.ollama_local import OllamaAdapter
    from ant_orchestrator.config.models import ModelEndpointConfig
    from ant_orchestrator.workers.documentation.composer_impl import LLMDocumentationComposer

    endpoint = ModelEndpointConfig(provider="ollama", model=_MODEL, base_url=_BASE_URL)
    return LLMDocumentationComposer(OllamaAdapter(endpoint, client=LiteLLMSdkClient()))


def test_ollama_provider_backed_create_slice(tmp_path: Path) -> None:
    write_fixture(tmp_path, brief="Summarise the release and list next steps for the handoff.")
    svc = build_services(tmp_path, composer=_live_composer())
    task = svc.create_task.create(title="live handoff")

    svc.run_workflow.execute(task.id.value)
    svc.resolve_approval.approve(task.id.value)

    target = tmp_path / CREATE_TARGET
    assert target.is_file(), "live provider slice did not publish the document"
    content = target.read_text(encoding="utf-8")
    for section in SECTIONS:
        assert f"## {section}" in content, f"missing required section {section!r}"

    conn = sqlite3.connect(str(tmp_path / ANT_DIRNAME / DATABASE_FILENAME))
    conn.row_factory = sqlite3.Row
    with conn:
        assert conn.execute("SELECT COUNT(*) c FROM worker_runs").fetchone()["c"] == 1
        result = conn.execute("SELECT result FROM execution_evidence").fetchone()["result"]
    # Sanitized: the durable envelope records digests/refs, never the raw model body.
    assert content.strip() not in result
    print(f"\n[CP7 OLLAMA] model={_MODEL} published {CREATE_TARGET} ({len(content)} chars)")
