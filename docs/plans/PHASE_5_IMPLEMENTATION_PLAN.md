# PHASE 5 — Documentation Ant: First Real Vertical Slice — Implementation Plan

**Trạng thái**: `PLANNED` (planning baseline; chưa bắt đầu implementation tại thời điểm ghi file).
**Nguồn**: bản brainstorming A–J đã được Product Owner duyệt ("PASS WITH MANDATORY IMPLEMENTATION PREFLIGHTS").
**Ngôn ngữ**: tiếng Việt (theo `CLAUDE.md §1`).

> Quy tắc plan: file này là planning baseline. Sau khi commit, **không** viết lại toàn bộ plan vì chi tiết nhỏ. Mỗi checkpoint được phép append `Preflight findings` / `Implementation deviations` (xem PF-8). Chỉ dừng hỏi PO khi có hard blocker hoặc cần đổi: Phase 5 scope / protected-frozen semantics / security boundary / durable recovery guarantee / provider strategy / Definition of Done.

---

## A. Baseline

| Mục | Giá trị (đã xác minh) |
|---|---|
| `develop` HEAD | `02cd79bc9559702686891bfe9ffaf14ce0b72e3b` (`docs(roadmap): mark phase 4 complete`) |
| Phase 4 completion report commit | `a814ebd929923b08801aa7de2fbcff880152db5b` |
| Quality gate gần nhất | `1219 passed, 7 skipped` (pytest); `scripts.quality.gate` 5/5 PASS; mypy strict; `pip check` clean |
| Working tree | clean tại thời điểm bắt đầu |
| Worker hiện tại | `src/ant_orchestrator/workers/stub.py` — `DeterministicStubAdapter` (no-op) |

**Nguyên tắc lịch sử**: không sửa lịch sử, không rebase/squash, không thay đổi commit closure Phase 0–4.

---

## B. Decisions (đã chốt) + claim cũ bị loại

### Đã chốt
- Production Documentation Ant dùng **LLM qua provider-neutral adapter** (`LLMAdapter` + `factory.py`); **deterministic fake** cho unit/integration/CI gate.
- **Một** provider-backed run qua **Ollama local** là evidence explicit/non-gate.
- **Fixture workspace** copy sang temporary nest; không mutate fixture source.
- **Single target per task** (một CREATE/UPDATE document target).
- Context được **chuẩn bị trước approval** và bind bằng **digest** (anti-TOCTOU).
- **Model không authoritative** cho operational facts.
- **Prepared-mutation journal** (durable artifact) làm recovery bridge.
- **System-managed artifacts** dưới `.ant/artifacts/<run>/<attempt>/`.
- Output `AGENT_OPERATING_MODEL §12` dùng **typed `WorkerExecutionReport`** map vào `WorkerRun` + `ExecutionEvidence`.
- **Workflow version theo semantics** (không chỉ topology).
- Protected policy dùng **policy object/config, không DB**.
- Advanced Windows path forms bị **deny fail-closed**.
- Protected exact list từ **repository audit**, không để PO đoán.
- **Không** over-claim semantic correctness tuyệt đối.
- **Không** Test Ant, không retrieval nâng cao, không sửa protected document.

### Default (đã quyết)
- Journal = durable artifact (không thêm bảng/migration trừ khi CP cần index, có versioning).
- Version bump: `WORKFLOW_DEFINITION_VERSION 2→3`, `GRAPH_STATE_SCHEMA_VERSION 1→2` (giá trị thực đã audit).
- Async bridge = `AsyncDependencyRunner` (facade mới; chưa có facade dùng chung — `application/ports/llm.py:9` xác nhận call site tự bridge).
- Artifact root = `.ant/artifacts/<run>/<attempt>/`.
- Protected enforce = Tier 1 (xem mục Protected Registry).

### Claim cũ bị loại bỏ (tích lũy)
| Claim cũ | Trạng thái | Thay bằng |
|---|---|---|
| Worker tự build context sau approval | ❌ Loại | Context prep off-graph trước approval + digest binding |
| "topology không đổi ⇒ giữ version" (I7 cũ) | ❌ Loại | Version theo semantics; bump def v2→v3; fail-closed |
| "Tin model files_changed rồi reconcile" | ❌ Loại | Model không authoritative cho operational facts |
| "All-or-nothing multi-file batch" | ❌ Loại | Single target/task; multi→reject |
| "Content-equal no-op làm idempotency" | ❌ Loại | Durable journal + digest authority |
| "asyncio.run rải trong logic Ant" | ❌ Loại | `AsyncDependencyRunner` facade |
| Protected "requirement/scope" mơ hồ / đoán path | ❌ Loại | Registry audit-based: Tier 1 exact + Tier 2 candidate |
| `ExecutionScope` chứa approval_ref/attempt_id tạo trước approval | ❌ Loại | `ExecutionProposal` (pre) → `ApprovedExecutionScope` (post) |
| "persist WorkerRun+Evidence+diff (1 UoW nguyên tử)" | ❌ Loại | Hai durability domain; journal bridge; DB chỉ persist refs/digests/records |

---

## C. Architecture

### Bốn lớp dữ liệu (tách bạch authority)

| Lớp | Tạo bởi | Authoritative cho | KHÔNG authoritative cho |
|---|---|---|---|
| `DocumentationTask` | Orchestrator | intent nghiệp vụ, `required_sections`, approved inputs, expected purpose | target path, scope, quyền |
| `ExecutionProposal` → `ApprovedExecutionScope` | Orchestrator | target, canonical scopes, manifest digest, energy authority, attempt | — (worker chỉ tiêu thụ) |
| `ModelCompositionDraft` | LLM | `proposed_content` và metadata nội dung được phép (`summary?`, `risks?`, `next_steps?`) | target, scope, files read, files changed, commands, diff, evidence, permission, result |
| `WorkerExecutionReport` (§12) | system (Ant/orchestration), tổng hợp từ audits + authoritative execution facts | tất cả operational facts | — |

### Component mới (production ≤350 dòng)

| Module | Trách nhiệm |
|---|---|
| `application/ports/document_worker.py` | `DocumentationTask`, `ModelCompositionDraft`, `WorkerExecutionReport`, enums |
| `application/ports/execution_scope.py` | `ExecutionProposal` (pre-approval), `ApprovedExecutionScope` (post-approval+attempt, immutable) |
| `application/services/context_preparation.py` | `ContextPreparationService`: build + digest + persist + proposal |
| `security/protected_path_policy.py` | `ProtectedPathPolicy` bọc `PathPolicy` + Windows fail-closed contract |
| `config/protected_paths.py` | `ProtectedRegistry` (exact/glob audit-based) + `PROTECTED_POLICY_VERSION` |
| `execution/prepared_mutation.py` | `PreparedMutationJournal` (durable artifact, monotonic status) |
| `execution/document_mutator.py` | `SafeDocumentMutator` (sync, single target, staging→publish→verify) |
| `execution/document_diff.py` | `DocumentDiff` (`difflib.unified_diff` + SHA-256) |
| `execution/artifact_root.py` | `ArtifactRoot` (path từ run/attempt id, encode/validate, ngoài write scope) |
| `execution/recovery.py` | `MutationRecovery` (recovery state machine) |
| `infrastructure/async_bridge.py` | `AsyncDependencyRunner` (sync facade, một loop boundary) |
| `workers/documentation/{composer,parser,validator,report,ant}.py` | Documentation Ant |
| `tests/support/{fixture_workspace,fake_composer}.py` | E2E fixture + deterministic fake |

### Component mở rộng
- `persistence/unit_of_work.py`: +`worker_runs`, +`execution_evidence`.
- `config/constants.py`: `WORKFLOW_DEFINITION_VERSION 2→3`, `GRAPH_STATE_SCHEMA_VERSION 1→2`.
- `workflows/nodes.py:context_node`: phát `context_package_ref` + `manifest_digest` thật.
- `workspace/layout.py`: +`ARTIFACTS_DIRNAME`.

### Luồng end-to-end (đầy đủ permission/validation/journal/publish/diff/energy)

> **Lưu ý ordering (PF-1)**: trong fresh execution, **permission + scope/digest verify + energy reverify phải xảy ra TRƯỚC khi đọc target và TRƯỚC khi gọi provider**. Sơ đồ dưới liệt kê các bước theo nhóm; thứ tự thực thi bắt buộc theo PF-1.

```
RunWorkflow.execute
 │
 ├─[PRE-APPROVAL, application boundary, off-graph]
 │   ContextPreparationService.prepare(DocumentationTask):
 │     1. bounded read allowed source inputs → ContextPackageBuilder.build → ContextPackage
 │     2. compute SHA-256: manifest_digest + mỗi source artifact digest
 │     3. persist immutable ContextPackage dưới .ant/artifacts/<run>/context/ (atomic + digest)
 │     4. energy ESTIMATE → reservation proposal
 │     5. build ExecutionProposal{run_id, logical_action_id, task_ref, candidate_target,
 │          operation, canonical_read_scope, canonical_write_scope, protected_policy_version,
 │          context_package_ref, manifest_digest, energy_reservation_proposal,
 │          expected_mutation, proposal_version, proposal_key}
 │        → proposal_digest (canonical repr, KHÔNG field biến động: không approval_ref/attempt_id)
 │
 ├─[GRAPH] WorkflowRunner.invoke:
 │   plan → context(REAL: context_package_ref + manifest_digest vào state, schema bump)
 │        → decision (significant_write / energy)
 │          REQUIRE_APPROVAL → prepare_intent(payload BIND: proposal_ref, proposal_digest,
 │             target, operation, read/write scope, protected_policy_version, manifest_digest,
 │             energy_reservation) → await_approval → interrupt()        [durable pause]
 │                                                                          │ resume
 │          [POST-APPROVE]                                                 ◄┘
 │            verify approval.proposal_digest == proposal (mismatch → fail closed)
 │            AttemptOrchestrator.before_execute → attempt_id (ổn định, reuse khi resume)
 │            reverify energy reservation
 │            assemble ApprovedExecutionScope{attempt_id, approval_ref, proposal_ref+digest,
 │               approved_target, approved_operation, canonical_scopes, context_ref+digest,
 │               protected_policy_version, energy_authority, artifact_root, idempotency_key}
 │            execute → DocumentationAnt.execute(DocumentationTask, ApprovedExecutionScope):
 │               [RECOVERY] nếu prepared journal tồn tại cho attempt → recovery state machine
 │                          (publish/finalize KHÔNG gọi LLM)
 │               [FRESH] theo ordering PF-1:
 │                 PERMISSION trước: canonicalize target từ scope; PathPolicy(WRITE);
 │                   ProtectedPathPolicy(protected_policy_version); Windows fail-closed;
 │                   verify operation + single-target; reverify energy reservation
 │                 a. bounded read current target → BEFORE state (UPDATE) / ABSENT (CREATE)
 │                 b. AsyncDependencyRunner.run(composer.compose) → ModelCompositionDraft (typed)
 │                 d. VALIDATION deterministic: required sections, structural correspondence
 │                 e. compute proposed_digest; compute unified diff (before→proposed)
 │                 f. persist sanitized BEFORE + PROPOSED + DIFF artifacts (atomic, SHA-256)
 │                 g. persist journal status=PREPARED (digests + refs + checksum); durable
 │                 h. PUBLISH target atomically (staging→atomic.publish); verify target digest
 │                 i. journal status=PUBLISHED
 │                 j. assemble authoritative WorkerExecutionReport (§12) từ audits  [PF-3]
 │                 k. DB UoW: persist WorkerRun + ExecutionEvidence + artifact REFERENCES/digests
 │                 l. verify/reconcile record identity + artifact digests
 │                 m. journal status=COMPLETED
 │               energy SETTLEMENT (ModelUsage hoặc fallback) gắn attempt  [PF-4]
 │               AttemptOrchestrator.after_execute settle attempt (chỉ sau settlement)
 │            → validate → review → persist_handoff → END
 │
 └─[POST-GRAPH] Pause/CompletionFinalizer (off-graph)
```

**Hai durability domains** (I11): filesystem artifacts (before/proposed/diff/journal) và SQLite records (WorkerRun/Evidence). **Không** UoW nguyên tử chung; **journal là recovery bridge**. Crash mỗi boundary phát hiện bằng `journal status + target digest + DB record existence`.

---

## D. Lifecycle / State machines

### D.1 Context preparation lifecycle
1. Context package được xây từ allowed source inputs (bounded read, no-scan).
2. Manifest và source digests được persist (immutable).
3. `ExecutionProposal` tham chiếu `manifest_digest`.
4. Approval bind `proposal_digest`.
5. Sau resume, package và manifest được verify lại.
6. Worker **không** rebuild context.
7. Package thiếu / đổi / digest mismatch → **fail closed**.

> Bất biến: object tạo **trước approval** (`ExecutionProposal`) KHÔNG chứa `approval_ref`; object tạo **trước attempt** KHÔNG chứa `execution_attempt_id`.

### D.2 Durable prepared-mutation protocol (ordering bắt buộc)
1. (PF-1) Permission preflight PASS.
2. Read current target qua bounded filesystem.
3. Capture authoritative BEFORE state (UPDATE) / `ABSENT` (CREATE).
4. Compose typed draft.
5. Validate proposed content và required sections (deterministic, **trước** publish).
6. Compute proposed digest.
7. Compute authoritative diff từ BEFORE state và proposed content.
8. Persist sanitized BEFORE / PROPOSED / DIFF artifacts (atomic, SHA-256).
9. Persist journal trạng thái `PREPARED`; đảm bảo durable.
10. Publish target atomically.
11. Verify target digest.
12. Journal → `PUBLISHED`.
13. (PF-3) Assemble `WorkerExecutionReport`; map → WorkerRun + ExecutionEvidence; persist DB UoW.
14. Verify/reconcile record identity + artifact digests.
15. Journal → `COMPLETED`; settle attempt/finalize workflow.

> Validation deterministic hoàn tất **trước** publish. KHÔNG dùng "publish rồi validation fail rồi rollback" làm normal flow.

### D.3 Journal nội dung tối thiểu
schema version; run id; attempt id; logical action id; proposal digest; approval reference; context digest; target canonical path; operation; previous digest; proposed digest; sanitized proposed-content artifact ref; before-snapshot artifact ref (UPDATE); diff artifact ref + digest; validation result ref; monotonic status; timestamps/sequence; journal digest/checksum. **Không** raw provider response/prompt.

### D.4 Recovery state machine
| Journal status | Target state | DB records | Recovery action | LLM? |
|---|---|---|---|---|
| (none) | — | — | fresh execute (D.2, 15 bước) | Có (lần đầu) |
| `PREPARED` | target có previous_digest (chưa publish) | thiếu | publish proposed artifact → verify → tiếp persistence | Không |
| `PREPARED` | target có proposed_digest (publish đã xong) | thiếu | coi publish thành công → `PUBLISHED` → persist records | Không |
| `PREPARED` | target digest ≠ prev & ≠ proposed | bất kỳ | **fail closed**: conflict/external mutation; không overwrite/rollback; controlled evidence | Không |
| `PUBLISHED` | target có proposed_digest | thiếu | persist WorkerRun/Evidence từ prepared artifacts | Không |
| `PUBLISHED` | target digest mismatch proposed | bất kỳ | **fail closed** + controlled recovery evidence | Không |
| `COMPLETED` | proposed_digest | tồn tại | idempotent no-op/finalize | Không |
| `PUBLISHED`/`COMPLETED` | proposed_digest | DB tồn tại nhưng journal chưa `COMPLETED` | reconcile record identity/digests qua unique/idempotency constraint → hoàn tất journal, **không duplicate** | Không |

Recovery dựa trên **unique/idempotency constraints** (DB) + **digest** (FS), không chỉ code-level check.

### D.5 Energy lifecycle (10 bước)
1. Estimate (pre-approval).
2. Reserve (reservation authority).
3. Approval binding (reservation gắn proposal/approval).
4. Reverify reservation khi tạo `ApprovedExecutionScope`.
5. Provider invocation.
6. Capture sanitized `ModelUsage` (hoặc conservative fallback nếu `ModelUsage.unavailable`).
7. Persist settlement gắn attempt.
8. Chỉ sau đó attempt mới có thể settle `SUCCEEDED` (PF-4).
9. Over-budget: `EnforcementPolicy.check_consumption` → `STOP`.
10. Recovery khi journal đã `PREPARED`: không gọi lại provider, không tạo consumption mới (không double-charge).

> Crash giữa provider response và energy settlement: settlement/fallback chạy theo controlled failure/finally path khi provider call đã xảy ra; raw exception không persist. Test/recovery rule bắt buộc **trước CP5 closure**.

---

## E. Invariants

| ID | Invariant |
|---|---|
| I1 | Worker mutate FS **chỉ** qua `SafeDocumentMutator`. |
| I2 | Operational facts (files_read/changed/commands/diff/result) **system-generated**; model không khai báo. |
| I3 | `result=SUCCESS` chỉ sau permission + journal `PREPARED` + publish + digest-verify + persistence + reconcile. |
| I4 | Worker tiêu thụ `ApprovedExecutionScope` immutable; target từ approved scope, không từ model. |
| I5 | Worker đọc **chỉ** ContextPackage đã approve; resume verify manifest digest; mismatch/thiếu → fail closed (anti-TOCTOU). |
| I6 | Mutation atomic + durable-journaled; recovery finalize từ prepared artifacts **không gọi lại LLM**; không partial mutation. |
| I7 | Workflow version phản ánh **semantics**; checkpoint Phase 4 (def v2) **fail-closed** dưới Phase 5 (def v3). |
| I8 | **Đúng một** document target/task; system artifact không tính vào `files_changed`; artifact root ngoài write scope. |
| I9 | Không raw prompt/output/exception trong GraphState/WorkerRun/Evidence/artifact. |
| I10 | Energy estimate→reserve→reverify→consume→settle gắn attempt; fallback bảo thủ khi usage thiếu; recovery không double-charge. |
| I11 | FS artifacts và SQLite records là **hai durability domain**; journal là recovery bridge; success chỉ khi cả hai reconcile. |
| I12 | `ExecutionProposal` (pre-approval) KHÔNG chứa `approval_ref`/`attempt_id`; `ApprovedExecutionScope` chỉ tạo sau approval + stable attempt id. |
| I13 | UPDATE persist BEFORE-snapshot + PROPOSED + DIFF (3 artifacts, SHA-256); CREATE before-state = `ABSENT` (không empty file mơ hồ). |

---

## F. Checkpoint plan

| CP | Mục tiêu | File/module | Invariant | Test bắt buộc | Evidence | Done khi | Không làm | Rollback/recovery boundary |
|---|---|---|---|---|---|---|---|---|
| **CP0** | Planning baseline + decision log + plan approval | `docs/plans/PHASE_5_IMPLEMENTATION_PLAN.md` | — | document verification | plan file + commit | PO PASS | code | revert plan commit |
| **CP1** | Typed contracts: task, proposal, approved scope, draft, report | `ports/document_worker.py`, `ports/execution_scope.py` | I2,I4,I12 | invariants; proposal không chứa approval/attempt; scope immutable; draft không authoritative | type tests | 4 lớp dữ liệu tách bạch | mutation thật | revert CP1 |
| **CP2** | Context prep off-graph + immutable manifest/digest + proposal/approval binding + state schema bump | `services/context_preparation.py`, `nodes.py:context_node`, `constants.py` | I5,I12 | build+digest; persist immutable; resume digest mismatch→fail closed; state v1→v2 guard | manifest+proposal digest | anti-TOCTOU chứng minh | worker logic | revert CP2 |
| **CP3** | Protected-path policy (audit-based registry) + Windows fail-closed contract | `security/protected_path_policy.py`, `config/protected_paths.py` | I4 | abs/`..`/symlink/prefix-collision/protected exact+glob/mixed-sep + Windows (drive-abs, `C:foo`, UNC, `\\?\`, `\\.\`, ADS) deny | path decision evidence | mọi rule canonical+test+policy_version | DB registry | revert CP3 |
| **CP4** | Before/proposed/diff artifacts + prepared journal + recovery state machine + single-file mutator + deterministic validation | `execution/{prepared_mutation,document_mutator,document_diff,artifact_root,recovery}.py`, `workers/documentation/validator.py`, `workspace/layout.py` | I1,I3,I6,I8,I11,I13 | D.2 15-step ordering; validation trước publish; recovery 8 trạng thái; digest conflict fail-closed; rollback; single-target; artifact durability (PF-7) | journal+before+proposed+diff artifact | crash mọi boundary recover được, không LLM | LLM call | discard staging; journal+digest authority |
| **CP5** | Documentation Ant + provider-neutral composition + async bridge + energy lifecycle | `workers/documentation/{composer,parser,report,ant}.py`, `infrastructure/async_bridge.py` | I2,I9,I10 | fake composer happy/fail; redaction; bridge (no active loop/timeout/cancel/no leak/no nested, call-once); energy D.5; crash provider↔settlement (PF-4); report từ audits | report+energy evidence | Ant chạy với fake, no fact-spoofing | graph wiring | swap về stub |
| **CP6** | Proposal→approval→attempt→scope assembly + graph/version guards + UoW mapping + recovery orchestration | `cli/workflow_composition.py`, `unit_of_work.py`, `constants.py`, `run_workflow.py` integration | I7,I11,I12 | def v2→v3 mismatch reject (structured); state v2 guard; UoW persist; resume→scope→execute; energy approval interrupt; recovery dispatch | version+approval+execution record | Phase 4 checkpoint fail-closed | provider live | composition revert; no silent migrate |
| **CP7** | Fixture E2E + 5 restart windows + digest-conflict + adversarial/security + provider-backed evidence | `tests/support/fixture_workspace.py` + tests; 1 Ollama live | toàn DoD | restart 1–5 + conflict; adversarial (mục G); 1 Ollama non-gate | full evidence bundle + live transcript | matrix xanh + 1 real run | live thành gate | fixture cô lập |
| **CP8** | Full regression + completion report + closure audit | `docs/plans/PHASE_5_COMPLETION_REPORT.md` | toàn bộ I1–I13 (audit) | full quality gate (`scripts.quality.gate`, pytest, mypy strict, `pip check`); regression Phase 0–4; `test_file_size`; no-pickle serialization | completion report DoD↔test↔evidence mapping; closure audit log | gate PASS; report map **mọi** DoD → test+evidence cụ thể; closure audit PASS; không requirement nào chỉ ghi "implemented" | sửa ROADMAP/Foundation/ADR; Documentation Ant sửa ROADMAP | revert CP8 doc commit |

**Ràng buộc thứ tự**: CP5 (Ant+LLM) chỉ bắt đầu sau CP1–CP4 (context/permission/durable mutation contracts đã hoàn thành). CP6 phụ thuộc CP1–CP5. CP7 phụ thuộc CP1–CP6.

**CP8 — ROADMAP note**: Documentation Ant **không** sửa `ROADMAP.md`. Nếu closure cần cập nhật trạng thái Phase 5 trong `ROADMAP.md`, đó là **governance action riêng** sau closure PASS — không phải output của Documentation Ant và không nằm trong worker vertical slice.

---

## G. Test & evidence matrix (Requirement → Test → Evidence → CP)

| DoD requirement | Test | Evidence | CP |
|---|---|---|---|
| Tạo/sửa doc thật qua graph | E2E CREATE + UPDATE | file + diff artifact | CP7 |
| Human approval interrupt/resume thật | resume APPROVE→execute | approval record + payload | CP6/7 |
| Context prepared off-graph + digest binding | prep service + proposal/approval bind | manifest+proposal digest | CP2 |
| Resume verify digest, mismatch fail-closed (anti-TOCTOU) | tamper manifest/proposal → fail closed | fail-closed evidence | CP2/7 |
| Proposal không chứa approval/attempt; scope post-approval | contract test | type evidence | CP1 |
| Energy estimate→reserve→reverify→consume→settle | full lifecycle; overrun→STOP; usage unavailable→fallback; recovery no double-charge | energy estimate/reservation/actual-fallback/settlement | CP5/7 |
| Worker trong execution boundary | mutate chỉ qua SafeDocumentMutator | path decisions | CP4 |
| Output §12 đầy đủ, system-assembled | report 8 trường từ audits | WorkerRun+Evidence | CP1/5 |
| Model không authoritative | model khai sai files/target/success/evidence → bị bỏ | adversarial evidence | CP5/7 |
| Artifact + diff thật + digest | diff = before→proposed, SHA-256 | diff artifact | CP4 |
| Approval binds proposal; ApprovedExecutionScope links approval to stable attempt | approval/scope binding test | approval row + scope link | CP6 |
| Execution record | WorkerRun SUCCEEDED | worker_run row | CP5/6 |
| **Không ghi ngoài allowed path** | abs/`..`/symlink/prefix/mixed-sep + Windows variants | DENY evidence | CP3/7 |
| **Không sửa protected doc** | write protected (exact+adr) → deny | PROTECTED_DOCUMENT deny | CP3/7 |
| **Không đọc ngoài manifest** | composer chỉ nhận ContextPackage; read-scope=manifest | manifest + read deny | CP2/5 |
| **Metadata không giả mạo facts** | model không có quyền khai files_changed | system-fact evidence | CP1/5 |
| Single target/task | task/model đòi 2 file → reject preflight | reject evidence | CP4/7 |
| Window 1: restart trước approval | re-enter AWAITING idempotent | approval pending | CP7 |
| Window 2: sau approval trước provider call | execute từ đầu; reuse attempt; LLM lần đầu | attempt reuse | CP7 |
| Window 3: sau PREPARED trước publish | publish từ journal, không LLM | journal PREPARED→PUBLISHED | CP7 |
| Window 4 (bắt buộc): sau publish trước DB persist | finalize từ artifacts, **không** double-LLM, **không** nội dung khác | journal+digest+persisted record | CP7 |
| Window 5: sau persist trước completion finalizer | CompletionFinalizer re-run | completion record | CP7 |
| Digest conflict (target digest ≠ prev & proposed) | external mutation → fail closed | conflict recovery evidence | CP4/7 |
| Failure không partial mutation | validation fail trước publish → discard | no-change snapshot | CP4/7 |
| Version semantics: Phase 4 fail-closed | def v2 re-enter → `WorkflowDefinitionMismatch` | structured version error | CP6 |
| FS+DB hai domain, journal bridge | crash giữa publish và DB → reconcile | journal+DB reconcile evidence | CP4/7 |
| Regression Phase 0–4 | full suite | 1219+ pass | CP8 |
| no-pickle serialization | state json-safe (manifest ref scalar) | serializer test | CP2/6 |
| No raw leak | redaction + no raw artifact | redaction evidence | CP5 |
| File ≤350 dòng | `test_file_size` | gate | CP8 |

**Phân tầng (không over-claim)**: "nội dung tương ứng task / không scope creep / không diễn giải lại frozen" = **structural guardrail + contract**, KHÔNG enforce nghĩa tuyệt đối — dành reviewer/retrieval phase sau.

### Restart windows (5) — bắt buộc
| # | Window | Expected recovery | Evidence |
|---|---|---|---|
| 1 | Trước approval | re-enter AWAITING_APPROVAL idempotent | approval pending |
| 2 | Sau approval, trước provider call | execute từ đầu; before_execute reuse attempt; LLM lần đầu | attempt reuse |
| 3 | Sau PREPARED draft, trước publish | publish từ journal, **không** gọi lại LLM | journal PREPARED→PUBLISHED |
| 4 (bắt buộc) | Sau publish, trước WorkerRun/Evidence persist | finalize persistence từ prepared (digest khớp), **không** double-LLM, **không** nội dung khác | journal+digest+persisted record |
| 5 | Sau persist, trước completion finalizer | CompletionFinalizer re-run (crash #7 path Phase 4) | completion record |

---

## H. Risk register

| Rủi ro | P | I | Prevention | Detection | Recovery | CP |
|---|---|---|---|---|---|---|
| Ghi ngoài allowed path | M | H | PathPolicy + canonicalize trước mutate | adversarial tests | discard staging | CP3 |
| Traversal/symlink/Windows path escape | M | H | `_is_symlink_escaping` + Windows fail-closed contract | symlink+drive/UNC/ADS tests | deny | CP3 |
| Sửa protected doc | M | H | ProtectedPathPolicy deny-by-default, registry audit-based | protected tests | deny+audit | CP3 |
| TOCTOU context approve↔use | M | H | prepare off-graph + digest binding + resume verify | digest mismatch test | fail closed | CP2 |
| Model giả mạo operational facts | M | H | model không authoritative | adversarial tests | bỏ draft facts | CP1/5 |
| Crash sau publish trước DB persist | M | H | journal bridge + digest authority | restart window 4 | finalize không LLM | CP4/7 |
| LLM retry sinh nội dung khác | M | H | journal digest authority (không content-equal) | window 3/4 | dùng prepared content | CP4 |
| Digest conflict / external mutation | L | H | digest verify trước/sau publish | conflict test | fail closed, không overwrite | CP4 |
| FS/DB hai domain lệch nhau | M | H | journal reconcile bridge | window 4/5 | reconcile, no duplicate | CP4/7 |
| Đọc rộng hơn manifest | M | M | composer chỉ nhận ContextPackage (no-scan) | read-scope test | deny | CP2/5 |
| Scope creep nội dung | M | M | structural validator + contract | section/anchor check | VALIDATION_FAILURE | CP4 |
| Multi-file giả crash-atomic | L | H | single target/task; multi→reject | preflight test | n/a | CP4 |
| Báo success không output | L | H | I3 success-after-verify | file-exists test | FAILED | CP4 |
| Silent resume Phase 4 dưới semantics mới | L | H | bump def v3; fail-closed | def v2→v3 mismatch test | reject structured | CP6 |
| Energy usage unavailable / over-budget | M | M | reservation + fallback bảo thủ + check_consumption STOP | energy test | conservative settle | CP5 |
| Async bridge leak/nested/double-call | M | M | facade chuyên trách, no active loop, no nested, call-once | bridge tests | sanitized error | CP5 |
| Khóa cứng provider | M | M | LLMAdapter qua factory; fake double | wiring test | — | CP5 |
| Live test gate flaky | M | M | Ollama explicit/non-gate, skip no-model | CI | skip | CP7 |
| Leak raw prompt/output | L | H | parse→typed, redaction, no raw artifact | redaction test | — | CP5 |
| Artifact corruption | L | M | digest verify khi recovery; size limit; no symlink follow | corruption test | fail closed | CP4 |
| File >350 dòng | M | L | package split documentation/ | `test_file_size` | tách module | CP8 |
| Phase 5 phình framework | M | M | 1 slice, không Test Ant/retrieval | review gate | cắt scope | CP0 |

---

## I. Protected registry (audit-based) + Windows contract

### Tier 1 — Confirmed protected (auto-deny, từ repo audit)
| Path (repo-relative canonical) | Lý do (audit) |
|---|---|
| `docs/product/FOUNDATION.md` | header `Trạng thái: Frozen Draft` |
| `docs/product/TECHNICAL_FOUNDATION.md` | header `Trạng thái: Frozen Draft` |
| `docs/product/MVP_SCOPE.md` | header `Trạng thái: Frozen Draft` (requirement/scope) |
| `docs/product/adr/ADR-0001-python-first-core.md` … `ADR-0006-separate-security-from-execution.md` (cả directory `docs/product/adr/`) | tất cả `Trạng thái: Accepted` (ADR convention = frozen) |
| `ROADMAP.md` | governance; prompt cấm worker tự sửa |

### Tier 2 — Candidate (PF-5): KHÔNG auto-protect, KHÔNG nằm trong default allowed write scope
| Path | Trạng thái audit | Ghi chú |
|---|---|---|
| `docs/product/AGENT_OPERATING_MODEL.md` | governance (Draft) | định nghĩa worker contract |
| `docs/product/DECISION_LOG.md` | Draft | nhật ký quyết định |
| `docs/product/CONTEXT_POLICY.md`, `ENERGY_POLICY.md`, `ADAPTER_CONTRACT.md`, `WORKFLOW_SPEC.md`, `MEMORY_AND_PHEROMONE_SPEC.md`, `PROJECT_STRUCTURE.md` | Draft | spec, chưa frozen |
| `CLAUDE.md` (root) | governance | hướng dẫn agent |

> PF-5: Tier 2 không tự động coi là frozen chỉ vì tên. Documentation Ant chỉ ghi đúng approved target. Thêm một Tier 2 vào protected registry sau này là **policy-versioned governance change**; không âm thầm đổi Draft → frozen/protected.

Registry có `PROTECTED_POLICY_VERSION` explicit. Mỗi rule: canonicalization, separator normalization, case-insensitive matching trên Windows / case-sensitive trên POSIX, prefix-collision tests.

### Windows path fail-closed contract (có unit tests + documented assumption)
Worker target phải là normalized relative path trong workspace. **Reject**: drive-absolute (`C:\...`), drive-relative (`C:foo`), UNC (`\\server\share`), device namespace (`\\?\`, `\\.\`), ADS / segment chứa colon không hợp lệ, path không canonicalize an toàn. POSIX giữ semantics tương ứng. **Không** hỗ trợ đầy đủ Windows device path — chỉ deny an toàn + document assumption.

---

## J. Implementation Preflight Clarifications

> Đây là interpretation bắt buộc của plan (PO mandate). Áp dụng khi implement; không tạo vòng revised plan mới.

**PF-1 — Permission trước read và provider call.** Fresh execution ordering: (1) verify proposal/approval/scope/context digest; (2) canonicalize approved target; (3) `PathPolicy`; (4) `ProtectedPathPolicy`; (5) verify operation + single-target; (6) reverify energy reservation; (7) đọc current target; (8) gọi provider. Không đọc target chưa permission; không gọi LLM cho target bị deny; không tiêu energy trước khi permission preflight PASS. (Sơ đồ mục C đặt compose trước vài bước chỉ là trình bày; implementation theo ordering này.)

**PF-2 — Approval bind proposal, không bind attempt.** Approval record bind: proposal ref + digest, target, operation, scopes, manifest digest, protected-policy version, energy reservation. Approval xảy ra trước khi attempt id tồn tại. Sau approval: `before_execute` tạo/lấy stable attempt id → tạo `ApprovedExecutionScope` link approval ref + attempt id. Không đổi attempt lifecycle để có attempt id trước approval.

**PF-3 — Report assembly trước DB persistence.** Sau publish: verify target digest → journal `PUBLISHED` → assemble `WorkerExecutionReport` từ (context/read audit, permission decisions, mutation result, before/proposed/diff artifacts, command audit, validation result, energy facts, risks/next steps hợp lệ) → map → WorkerRun + ExecutionEvidence → persist DB UoW → verify/reconcile identity + digests → journal `COMPLETED`. Không persist records trước rồi mới tạo report. Không lưu raw provider output.

**PF-4 — Energy settlement trước attempt success.** Theo D.5. Nếu provider/worker thất bại: settlement/fallback chạy theo controlled failure/finally path khi provider call đã xảy ra; raw exception không persist; retry/recovery không double-charge; journal `PREPARED` → recovery không gọi lại provider, không tạo consumption mới. Crash provider↔settlement có test/recovery rule **trước CP5 closure**.

**PF-5 — Tier 2 policy.** Phase 5 enforce Tier 1 (mục I). Tier 2 không auto-frozen, không trong default write scope; thêm sau = policy-versioned governance change.

**PF-6 — Idempotency authority.** Canonical chain: `run / logical action / proposal digest / stable attempt`. Implementation phải xác định: key nhận diện logical action; key nhận diện proposal; key cho DB unique constraint; key tìm journal; retry nào reuse attempt; regroup nào tạo attempt mới. Tái dùng entity hiện có (`operation_id` là idempotency key, `AttemptOrchestrator` stable attempt) — **không** tạo nhiều khóa semantics chồng lấn không định nghĩa quan hệ; không đổi domain model rộng hơn Phase 5 cần.

**PF-7 — Artifact/journal durability.** Trước khi CP4 done, verify `workspace/atomic.py` đáp ứng: temp file cùng filesystem; atomic replace; flush file; flush parent directory khi platform hỗ trợ; no symlink following; digest verification; bounded artifact size. Nếu thiếu phần nào → mở rộng tối thiểu hoặc document supported durability contract. Không over-claim crash durability mạnh hơn implementation thực tế.

**PF-8 — Plan deviation discipline.** Sau planning baseline: không viết lại toàn bộ plan vì chi tiết nhỏ. Mỗi CP được phép append `Preflight findings`/`Implementation deviations` ghi: phát hiện; ảnh hưởng; quyết định; test/evidence; có đổi scope không. Nếu không đổi mục tiêu/DoD/trust boundary/frozen decision → tiếp tục. Chỉ dừng hỏi PO khi hard blocker hoặc cần đổi: Phase 5 scope / protected-frozen semantics / security boundary / durable recovery guarantee / provider strategy / DoD.

---

## K. Definition of Done (mapping)

| DoD (ROADMAP/prompt) | Test/Evidence | CP |
|---|---|---|
| Scenario tạo/sửa doc thật chạy E2E qua graph | E2E CREATE/UPDATE | CP7 |
| Human approval interrupt/resume thật | resume APPROVE→execute + approval record | CP6/7 |
| Context manifest dùng + lưu evidence | prep service + manifest digest evidence | CP2 |
| Energy budget enforce | energy lifecycle D.5 + evidence | CP5/7 |
| Worker chạy trong execution boundary | mutate qua SafeDocumentMutator | CP4 |
| Output contract đầy đủ §12 | WorkerExecutionReport 8 trường | CP1/5 |
| Artifact + diff thật | diff artifact + SHA-256 | CP4 |
| Approval record | approval row bind proposal | CP6 |
| Execution record | WorkerRun row | CP5/6 |
| Test worker không ghi ngoài allowed path | path adversarial + Windows | CP3/7 |
| Test worker không sửa protected document | protected deny | CP3/7 |
| Test worker không đọc/dùng context ngoài manifest | read-scope + manifest | CP2/5 |
| Test metadata không giả mạo diff/file output | model-not-authoritative adversarial | CP1/5 |
| Failure path không partial mutation | validation-fail discard + recovery | CP4/7 |
| Toàn bộ quality gate PASS | `scripts.quality.gate` + pytest + mypy + pip check | CP8 |
| Completion report liên kết từng DoD với test/evidence | report mapping (không "implemented" suông) | CP8 |

---

## L. Out of scope (Phase 5 KHÔNG làm)
Test Ant; retrieval nâng cao; semantic indexing / vector DB; tự động sửa protected document; Documentation Ant tự cập nhật `ROADMAP.md` / Foundation / Technical Foundation / frozen ADR; general-purpose documentation platform; multi-ant collaboration; performance scoring/AES; learning / tự điều chỉnh permission; mở rộng nhiều loại worker; multi-file transactional mutation; thay đổi kiến trúc Phase 3/4 nếu không có blocker được chứng minh.

---

## M. Planning baseline commit rule
1. Ghi file này.
2. Document-only verification (file tồn tại; A–M đầy đủ; CP0–CP8 đầy đủ; không dòng cắt/placeholder; recovery state machine + test matrix nguyên vẹn; không sửa Foundation/Technical Foundation/ADR/ROADMAP/source).
3. `git diff` chỉ chứa planning document.
4. Commit planning baseline **riêng**: `docs(plan): add phase 5 documentation ant implementation plan`.
5. Sau commit: bắt đầu CP1 → CP8 theo thứ tự; mỗi CP chạy test bắt buộc + regression phù hợp + commit riêng; không cập nhật ROADMAP trước closure PASS.

---

## N. Append-only implementation notes (deviations)

### CP2 (commit feat(context): immutable phase 5 context preparation)
- **Vị trí ContextPreparationService**: tách 3 module thay vì 1 (`application/services/context_preparation.py` như §C liệt kê), do contract import-boundary: `application/services` **không** được import `ant_orchestrator.context`. Giải pháp: port `application/ports/context_preparation.py` (`ContextSourcePreparer` + DTO trả về ref/digest JSON-safe); impl `context/preparation.py` (`ContextSourcePreparerImpl` build+digest+persist); service `application/services/context_preparation.py` chỉ assemble `ExecutionProposal`. Không đổi scope/trust boundary/DoD — chỉ phân lớp DI cho đúng boundary.
- **Quyết định version**: bump `GRAPH_STATE_SCHEMA_VERSION 1→2` (state mang `context_package_ref`+`manifest_digest`, anti-TOCTOU; checkpoint pre-CP2 fail-closed qua `GraphStateSchemaMismatch`). **Giữ** `WORKFLOW_DEFINITION_VERSION=2`, hoãn 2→3 tới CP6: CP2 không thêm node/edge (topology bất biến) và state-schema bump đã fail-close mọi checkpoint cũ → bump trục thứ hai là dư thừa. Không quyết định chỉ dựa trên topology; căn cứ là resumable semantic incompatibility đã được state-schema guard phủ.
- **ContextPackageStore boundary**: nhận `artifacts_root: Path` đã resolve (composition root dựng `<workspace>/.ant/artifacts` từ `workspace.layout`), không import `workspace` (context-layer cấm). `context_package_ref` là path tương đối so với artifacts_root; verify chặn escape ngoài root (traversal/symlink) fail-closed.
- **context_node**: promote `context_package_ref`+`manifest_digest` thật khi có (mirror vào `context_ref`, KHÔNG placeholder). Đường legacy không có prepared context (Phase-4 stub) giữ `ctx:` ref tạm — CP5/CP6 thay thế.

### CP3 (commit feat(security): add protected document path policy)
- **Vị trí registry**: đặt ở `security/protected_paths.py` thay vì `config/protected_paths.py` (§C). Lý do: `test_security_layer_is_pure` cấm `security/` import `config/`; `ProtectedPathPolicy` (security) cần registry → registry phải nằm trong security/. `PROTECTED_POLICY_VERSION` ở đây. Không đổi scope/DoD.
- **ADR rule**: chọn **directory rule** `docs/product/adr/` (rule nhỏ-nhất-an-toàn) vì audit: cả 6 ADR đều `Trạng thái: Accepted` (đồng nhất → không cần exact-file). Registry reject exact rule nằm trong directory rule (tránh trùng/xung đột).
- **Tier 1 audit-confirmed**: `docs/product/FOUNDATION.md`, `TECHNICAL_FOUNDATION.md`, `MVP_SCOPE.md` (Frozen Draft), `ROADMAP.md` (root, Active governance), dir `docs/product/adr/`. Tier 2 (AGENT_OPERATING_MODEL, DECISION_LOG, CONTEXT/ENERGY/ADAPTER/WORKFLOW/MEMORY specs, PROJECT_STRUCTURE, CLAUDE.md) **không** trong registry (PF-5).
- **Windows lexical guard cross-platform**: reserved device names + trailing dot/space + colon + UNC/device prefix kiểm tra **thuần lexical, áp dụng mọi OS** (fail-closed bất biến giữa POSIX/Windows; test chạy được trên POSIX CI). Chỉ **case-folding khi match protected** mới gated theo platform (Windows case-insensitive, POSIX case-sensitive) qua flag inject. Không hỗ trợ đầy đủ Windows device path — chỉ deny an toàn (documented assumption).
- **Composition**: một pipeline canonical duy nhất — lexical guard → `PathPolicy` (scope/traversal/symlink, tái dùng nguyên vẹn) → repo-relative → `ProtectedRegistry`. `DenyReason` mở rộng additive (PROTECTED_DOCUMENT, UNSAFE_WINDOWS_PATH, PATH_CANONICALIZATION_FAILED, UNSUPPORTED_POLICY_VERSION, UNSUPPORTED_OPERATION, INVALID_SCOPE). `WORKFLOW_DEFINITION_VERSION` **giữ nguyên** (CP3 không chạm persisted workflow semantics).

### CP4 (commit feat(execution): add durable document mutation journal)
- **Vị trí validator**: `execution/document_validation.py` thay vì `workers/documentation/validator.py` (§F). Lý do: `execution/` (mutator) không được import `workers/` theo boundary; validator deterministic là một phần của mutation substrate. Không đổi scope/DoD.
- **Artifact root inject**: `SafeDocumentMutator`/`ArtifactRoot` nhận `artifacts_root: Path` đã resolve (composition root dựng `<workspace>/.ant/artifacts`); execution/ không import `workspace` (cùng pattern CP2 store). Refs tương đối artifacts_root; `resolve_ref` chặn escape/symlink fail-closed.
- **BEFORE read đồng bộ bounded**: đọc target trước-state bằng sync bounded read (size cap + NUL/utf-8 check) thay vì `BoundedFileSystemAdapter` async (async bridge là CP5). Permission vẫn chạy **trước** read.
- **No-op policy (line-ending)**: NO_CHANGE quyết định theo **universal-newline logical lines** (CRLF/LF-insensitive) — khác biệt thuần line-ending không coi là mutation; publish ghi `content` verbatim (utf-8 LF), digest trên đúng bytes đã publish.
- **Directory/permission-layer reject**: target là directory/không-file bị `PathPolicy` từ chối ở permission layer → `PERMISSION_DENIED` (reason `not_a_file`) trước cả mutator self-check; vẫn fail-closed, không tạo artifact/journal.
- **Biên CP4 = `PUBLISHED`**: journal dừng ở PUBLISHED + digest-verify; `COMPLETED` + persist WorkerRun/Evidence + reconcile là CP6. Recovery state machine thuần (typed `DbObservation`), không đọc DB thật, không gọi LLM. External mutation/digest conflict → fail closed, không overwrite/rollback.
