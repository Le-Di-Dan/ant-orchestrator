# Phase 5 Completion Report — Documentation Ant: First Real Vertical Slice

## A. Executive verdict

**PHASE 5 CLOSURE AUDIT: PASS**

The symlink-capability blocker reported at CP7 is RESOLVED with real native evidence
(9/9 symlink security tests pass on Linux at the committed HEAD). All Definition-of-Done
items map to tests with runtime/artifact evidence; the full default quality gate is green.
The live-provider (Ollama) slice is non-default supplementary evidence — one real pass was
recorded; re-runs are intermittent (see §K) — and is not a closure gate.

## B. Baseline and commit chain

Linear history on branch `develop`, in checkpoint order, no WIP/out-of-scope commits:

- Planning: `f22e963` · CP1 `e697747` · CP2 `1c24eff` · CP3 `194a159` · CP4 `e623955`
- CP5 `fd9b76d` · CP6 `5a34345` · CP7 `6cbb9f7`
- CP8 preflight correction (test-only): `97bfc76`
- **Implementation audit HEAD**: `97bfc76`; working tree clean at that point.
- Completion report (this document, initial evidence commit): `542272b`.
- ROADMAP governance closure (Phase 5 → `COMPLETED`, status line only): `36715e7`.
- Audit-trail correction (this revision of the report): a separate commit created *after* `36715e7`,
  which becomes the **final HEAD**. The ROADMAP commit `36715e7` is NOT the final HEAD. (A commit
  cannot embed its own hash; the final HEAD hash is recorded in the closure report accompanying this
  correction.)
- **Final working-tree status**: clean after the correction commit.

No protected/governance document (Foundation, Technical Foundation, MVP Scope, ADR) was modified in
CP1–CP8. The only ROADMAP change is the single Phase-5 status line in `36715e7`.

## C. Scope delivered

Real Documentation Ant wired into the durable Phase-4 workflow: context preparation before
approval → `ExecutionProposal` + digest → approval interrupt/resume → stable attempt →
`ApprovedExecutionScope` → provider-neutral composition → safe single-document mutation →
before/proposed/diff artifacts → WorkerRun/ExecutionEvidence/energy persistence in one UoW
→ mutation journal `PUBLISHED→COMPLETED` → attempt settlement → workflow completion.

## D. Architecture and trust boundaries

- **Intent vs authority**: `DocumentationTask` carries no path/permission/attempt authority;
  authority lives in `ExecutionProposal` (pre-approval) and `ApprovedExecutionScope` (post).
- **Model vs system**: `ModelCompositionDraft` is authoritative only for content; every
  operational fact (files/commands/result/evidence/energy) is system-assembled. Prohibited
  model keys are rejected by the parser.
- **Context authority**: immutable context package + manifest/source digests, verified before
  use; tamper/missing/corrupt fail closed; worker never rebuilds context.
- **Receipt vs journal**: composition receipt = provider-phase authority; mutation journal =
  recovery bridge between the filesystem and SQLite durability domains.
- **Ordering**: DB commit → journal COMPLETED → attempt SUCCEEDED (never the reverse).

## E. DoD evidence matrix (DoD → test → result → evidence → checkpoint)

- Real Ant, no stub on prod doc path → `test_phase5_cp7_e2e::test_create_vertical_slice_e2e`
  → PASS → document published, 1 provider call, stub unused → CP6/CP7.
- Provider-neutral adapter, fake only in tests → `test_phase5_cp6_composition` → PASS →
  `build_documentation_execution` injects `DurableEnergyLifecycle`, fail-closed config → CP6.
- Context before approval, real manifest/digest → `test_phase5_cp6_preparation` +
  `cp7_e2e` → PASS → `proposal_ref/digest`, `context_package_ref` (no `ctx:` placeholder) → CP6.
- Proposal/approval digest binding → `cp6_preparation::test_bind_approval_*`,
  `cp6_integration::test_proposal_digest_tamper_fails_closed` → PASS → fail-closed mismatch → CP6.
- Stable attempt after approval; immutable scope → `cp6_integration`, `cp7_e2e` → PASS →
  attempt reused on recovery; scope assembled from approved authority → CP6.
- Energy estimate/reservation/reverify/settle, no double-charge → `cp5_documentation` (energy),
  `cp6_persistence::test_conflicting_energy_fails_closed`, `cp7_e2e` → PASS → 1 energy row,
  over-budget no-success, recovery no re-charge → CP5/CP6.
- Permission before provider; protected/escape/traversal/Windows/symlink → `cp3_protected`,
  `test_path_policy::TestSymlink`, `cp4_mutation`, `cp7_e2e::out_of_scope` → PASS (see §H) → CP3/CP4.
- Safe mutation: CREATE/UPDATE, section validation, before/proposed/diff, atomic publish,
  digest verify, conflict fail-closed → `cp4_mutation`, `cp7_e2e` CREATE+UPDATE → PASS → CP4/CP7.
- Durable recovery: receipt IN_DOUBT, journal, five windows, no double provider/publish/rows →
  `cp5_documentation` (recovery), `cp6_integration::recovery_window4`, `cp7_e2e` (W1, W5) → PASS → §G.
- Output §12 (8 fields, system-derived) → `test_phase5_contracts`, `cp5_documentation` → PASS → CP1/CP5.
- Evidence bundle linked + sanitized → `cp7_e2e::test_evidence_bundle_links_and_no_leak` → PASS → §F.
- Security/no-leak, no-pickle, versioned bounded envelope → `cp6_foundation`, `cp7_e2e`,
  Phase-4 no-pickle suite → PASS → §H.
- Versioning: def 3, schema 2, old checkpoint fail-closed → `test_workflow_version_guards`,
  `test_cp8_version_guards` → PASS → CP6.
- Deterministic identity chain, idempotent reuse vs conflict → `cp6_foundation`,
  `cp6_persistence` → PASS → CP6.

No requirement is recorded as merely "implemented/works/tested manually" without a named test.

## F. Vertical-slice evidence

- **CREATE** `docs/handoffs/HANDOFF-001.md`: run→pause (provider calls 0, target absent) →
  approve→resume → 1 provider call → file created with all required `## ` sections → 1 WorkerRun
  + 1 Evidence + 1 energy row → attempt SUCCEEDED → task COMPLETED. Evidence envelope
  `target_digest == sha256(published)`; all artifact refs (journal/receipt/proposed/before/diff)
  resolve under the system artifact root; refs are repo-relative; no raw model body in the DB row.
- **UPDATE** of an existing in-scope doc: stale content replaced by approved proposed content;
  required sections valid; exactly one WorkerRun + one Evidence row.

## G. Restart/recovery evidence (windows 1–5)

- **W1** (before approval): re-enter → same `WAITING_FOR_APPROVAL`, approval not recreated
  (`first.approval_id == second.approval_id`), provider 0, no mutation, no WorkerRun —
  `cp7_e2e::test_restart_window1_before_approval_is_idempotent`.
- **W2** (after approval, before provider invocation): crash with a post-approval, post-reservation
  receipt and NO durable draft yet. On resume the persisted approval/reservation and the stable
  attempt are reused (not recreated), the immutable scope is reused, and the provider is invoked for
  the FIRST time only after resume —
  `cp5_documentation::test_recover_reserved_receipt_resumes_fresh`
  (RESERVED receipt → `composer.calls == 1`, `control is None`, no draft existed before the injection
  point). The provider-boundary sibling proves no duplicate provider call across an in-flight
  invocation: `cp5_documentation::test_recover_invoking_receipt_is_in_doubt`
  (INVOKING → IN_DOUBT, `composer.calls == 0`).
- **W3** (after durable draft / composition receipt COMPLETED, before publish): crash with the draft
  artifact already durable. On resume the draft/proposed artifacts are reused, the provider is NOT
  called again, energy is settled exactly once (not a second time), and publish continues from the
  durable state with no new content generated —
  `cp5_documentation::test_recover_completed_receipt_reuses_draft`
  (COMPLETED receipt + durable draft → `composer.calls == 0`, receipt → `ENERGY_SETTLED`) and
  `cp5_documentation::test_recover_energy_settled_no_journal_reuses_draft`
  (lost journal + published file → draft reused, provider not called, re-publish from durable draft).
- **W4** (after publish, before DB persistence/settlement): a STARTED attempt that already published
  the target + durable receipt/journal but was never settled → persist+reconcile, journal
  `COMPLETED`, the same stable attempt reused (`attempt_ref` unchanged), provider not called again,
  no duplicate rows, no re-publish —
  `cp6_integration::test_recovery_window4_reuses_attempt_no_second_provider_call`,
  `cp5_documentation::test_recover_after_publish_uses_mutation_recovery`,
  `cp6_persistence` idempotent replay.
- **W5** (after commit/finalize): stray re-run rejected (`WorkflowStateError`), no duplicate
  provider call or WorkerRun — `cp7_e2e::test_post_completion_replay_does_not_duplicate`.
- Provider ambiguity: receipt INVOKING → IN_DOUBT, no auto-retry, no mutation, no success —
  `cp5_documentation::test_recover_invoking_receipt_is_in_doubt`.

## H. Security/adversarial evidence

Nine symlink/alias security tests are the core of the resolved CP7 blocker; they pass natively on a
Linux filesystem (reproducible command/environment in §J). Each maps to a concrete scenario:

- protected-document alias → `cp3_protected::test_symlink_alias_to_protected_denied`,
  `cp7_e2e::test_symlink_alias_to_protected_target_capability`
- workspace escape → `path_policy::TestSymlink::test_symlink_escapes_scope`,
  `cp3_protected::test_symlink_escaping_workspace_denied`
- parent-directory symlink escape → `path_policy::TestSymlink::test_parent_symlink_escapes_scope`
- broken symlink denied → `path_policy::TestSymlink::test_broken_symlink_denied`
- write via a symlinked parent (escape) →
  `path_policy::TestSymlink::test_write_via_symlinked_parent_outside`
- safe in-scope internal symlink (allowed by design) →
  `path_policy::TestSymlink::test_internal_symlink_within_scope`
- symlink swap before publish — UPDATE through an escaping symlink →
  `cp4_mutation::test_update_symlink_target_unsafe` (PERMISSION_DENIED `outside_write_scope`, target
  untouched; this expected-outcome was corrected in CP8 `97bfc76`)

Result: **9 passed, 0 skipped, 0 failed**. Out-of-scope write target → permission denied before
provider (`cp7_e2e::test_adversarial_out_of_scope_target_fails_closed`); artifact-root escape →
rejected (`cp4_mutation::test_artifact_root_rejects_escape`). Proposal-digest / approval-binding
tamper → fail-closed (`cp6`). Model attempting to declare operational facts → parser rejection
(`cp5`). No raw prompt/output/exception/secret/host-absolute-path in graph state, DB, evidence, or
artifacts.

## I. Provider-backed evidence

- Command:
  `ANT_OLLAMA_E2E=1 python -m pytest tests/test_phase5_cp7_ollama.py::test_ollama_provider_backed_create_slice`
  (non-default; skipped in the default gate via the `ANT_OLLAMA_E2E` guard). Provider/model
  identifier (sanitized): `qwen2.5-coder:7b` — local Ollama via the LiteLLM seam
  (`OllamaAdapter` → `LiteLLMSdkClient`).
- A real run drove the full production path (graph → approval → resume → real provider → strict
  typed-JSON parse → required-section validation → publish → persist → complete → settle) and
  published a handoff containing every required `## ` section (the test asserts each `SECTIONS`
  entry is present). Durability/no-leak validated in the same test: exactly one `worker_runs` row,
  and the persisted `execution_evidence.result` does NOT contain the published body
  (`content.strip() not in result`) — only digests/refs are stored.
- Reproducibility limitation (honest): the successful PASS was observed only as live `pytest`
  output (PASS plus the printed `[CP7 OLLAMA] model=… published … chars` line). The run uses a
  per-test `tmp_path` workspace that is not retained, so no durable run ID, attempt ID, or
  evidence-bundle artifact survives outside that test run; the pass is not re-derivable from a
  stored artifact. Re-runs are intermittent (see §K). No run ID, timestamp, or artifact reference
  is fabricated here.

## J. Quality gates (HEAD `97bfc76`)

- Ruff lint: pass (`All checks passed!`) · Ruff format check: **PASS — `333 files already
  formatted`** (check-only, `ruff format --check`; no file was modified) · Mypy strict: 191 files,
  no issues · File-size: no production file > 350 lines · `pip check`: no broken requirements ·
  Import-boundary: 26 passed.
- Full default pytest: **1412 passed, 12 skipped, 0 failed** (~169s).
- Native Linux symlink suite — **reproducible run**: source copied from a read-only bind mount into
  the container's native Linux filesystem (`docker run --rm -v <repo>:/src:ro python:3.11`, then
  `cp -r /src/{src,tests,pyproject.toml,README.md} /work`); `df -T /work` reports `overlay` and the
  `ln -s` capability probe succeeds before the run — this is a native Linux filesystem, NOT a
  Windows-backed bind mount. Image `python:3.11`
  (digest `sha256:9800957d2a88867f853ce6072ae1669e37fa269cc6f76009fa1aef4757f62212`),
  Python 3.11.15, pytest 9.1.1. Source identical to commit `97bfc76` (only docs changed after it).
  Command:
  `python -m pytest tests/test_path_policy.py::TestSymlink tests/test_phase5_cp3_protected.py::test_symlink_alias_to_protected_denied tests/test_phase5_cp3_protected.py::test_symlink_escaping_workspace_denied tests/test_phase5_cp4_mutation.py::test_update_symlink_target_unsafe tests/test_phase5_cp7_e2e.py::test_symlink_alias_to_protected_target_capability`.
  Result: **9 passed, 0 skipped, 0 failed** (0.37s).
- Skips in the default suite: host-dependent symlink markers (verified above on Linux) and the
  explicit non-default live-Ollama test. Phase 5 added net new tests over the Phase-4 baseline
  across CP1–CP8 with no regressions.

## K. Known limitations

- Provider `IN_DOUBT` is a controlled terminal state with NO automatic retry; no manual
  retry/regroup orchestration is built in Phase 5.
- Context preparation concurrency contract is **single-process** (immutable persist-by-identity;
  same identity+digest reuse, differing digest conflict). No distributed-lock framework.
- Filesystem durability uses atomic replace + best-effort fsync. Parent-directory fsync is
  capability-dependent and is omitted where unsupported; this limitation is documented and the
  implementation does not claim a stronger durability guarantee on those platforms.
- Single-document mutation target only.
- Semantic correctness of generated content is not guaranteed (validation = required sections
  + system contract, not meaning).
- **Live-provider test is non-default and intermittent**: the strict typed-JSON parser correctly
  rejects malformed model output, and the local 7B model frequently emits JSON with unescaped
  newlines inside multi-line content, so a given live run may fail to parse. One real pass was
  recorded; reliable structured output would require provider JSON-mode wiring (a request-contract
  change) that is out of Phase 5 scope. The default deterministic-composer gate is authoritative.
- **Symlink evidence requires a symlink-capable host** (verified here via Docker `python:3.11`);
  the Windows dev host cannot create symlinks, so the default Windows suite skips those markers.

## L. Out-of-scope confirmation

Not implemented (correctly): Test Ant, advanced retrieval / vector DB, multi-ant collaboration,
multi-file transactional mutation, protected-document modification flow, automatic ROADMAP
updates by a worker, performance/AES learning, provider-specific graph logic, general ACL/RBAC,
generic distributed transactions. No scope creep observed.

## M. Security / no-secret audit

This report contains no raw prompt, raw provider output, raw exception, secret, or host-absolute
path. Evidence references are repo-relative or sanitized identifiers; the durable evidence
envelope is typed, versioned, and bounded, and fails closed on an unsupported version.

## N. File-size / code-quality audit

No production file exceeds 350 lines. Integration logic lives in the `integration/` package
(not in the 327-line `ant.py`). Energy settlement math is shared (no duplicate pipeline). The
production composition uses `DurableEnergyLifecycle` (never the in-memory CP5 lifecycle, which is
test-only). The legacy `ctx:` context fallback exists only for Phase-4/legacy runs and is not
reachable on the Phase-5 production documentation path (which binds proposal/context refs and
fails closed without them). No broad exception swallowing; no unversioned free-form JSON.

## O. Rollback boundaries

Planning `f22e963` → CP1–CP7 (`e697747`…`6cbb9f7`) → CP8 test correction `97bfc76` → completion
report `542272b` → ROADMAP governance `36715e7` → this audit-trail correction (separate commit,
final HEAD). Each layer is additive/isolated and revertible independently; reverting the correction
or the governance commit touches neither source nor tests.

## P. Closure decision

- Verdict: **PHASE 5 CLOSURE AUDIT: PASS**.
- Remaining blocker: none (symlink capability evidence obtained and reproduced on a native Linux
  filesystem — §H/§J).
- Completion report: committed (`542272b`; finalized by this audit-trail correction commit).
- ROADMAP: Phase 5 marked `COMPLETED` in governance commit `36715e7` (status line only).
- Final HEAD: this audit-trail correction commit, created after `36715e7`; the ROADMAP commit is
  NOT the final HEAD.
- Final working tree: clean.
- Phase 6: NOT started; no branch merge performed. Repository is ready for next-phase planning.
