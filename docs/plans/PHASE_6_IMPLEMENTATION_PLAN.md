# PHASE 6 — Test Ant, Retry/Regroup/Escalate & MVP Workflow Completion — Implementation Plan

> **Trạng thái plan**: **READY_WITH_CHECKPOINT_PREFLIGHTS** (blocker governance đã được Product Owner
> gỡ — `ADR-0007-local-container-isolation-for-test-ant.md` phê duyệt local Docker isolation cho Test
> Ant; xem §N). Sẵn sàng chuyển sang implementation (CP1 trở đi).
> **Loại task**: PLANNING ONLY (chưa implement). **Canonical artifact**.

---

## Context

Phase 5 đã đóng (HEAD `9e6c026`). Phase 6 hoàn tất vòng lặp MVP hai worker (Documentation Ant + Test
Ant) với phân loại failure, retry/regroup/escalate có giới hạn, **execution isolation thật**,
energy/audit/handoff đầy đủ → Full MVP Candidate. Hạ tầng tái dùng đã có (routing retry/regroup/escalate,
bounded execution, command policy, energy đa-resource, attempt orchestration, handoff repo). Phase 6 =
lắp ráp + domain phân loại + worker đọc-only **chạy trong isolation backend enforce được**.

> **Trọng tâm correction:** (1) isolation phải là **enforcement boundary thật** (OS/container read-only
> mount), KHÔNG phải temp-copy+cwd+env+digest; (2) materialization **giữ nguyên byte** (không redact
> source); (3) **plain timeout KHÔNG retry** (chỉ transient có evidence mới retry); (4) energy `RETRIES`
> ghi **delta per-attempt** (không cumulative → tránh overcount); (5) bỏ claim "PATH chặn git
> child-process" — isolation mới là boundary; (6) cập nhật CP2/CP3/CP4/CP6/CP7.
> **Governance (2026-06-27):** Product Owner **phê duyệt phương án A** và ban hành `ADR-0007` (Accepted)
> cho phép local Docker isolation (read-only mount) riêng cho Test Ant → blocker đã gỡ; kết luận chuyển
> từ BLOCKED sang **READY_WITH_CHECKPOINT_PREFLIGHTS** (§N).

---

## A. Repository audit

- **Branch**: `develop` · **HEAD**: `9e6c026` · **Working tree**: clean. ROADMAP Phase 6 = `NOT_STARTED`.
- **Đã đọc**: ROADMAP §Phase 6/§9/§12; PHASE_5 plan + completion report (§J Docker evidence, §K/§L);
  MVP_SCOPE §4.9/§6/§7/§8; **ADR-0006** (tách security/execution — đóng băng "không container sandbox
  trong MVP"); enums, constants, energy port/measurement, bounded_shell/bounded_fs, command_policy,
  graph/graph_support/routing/nodes/attempt_orchestrator, documentation ant, run_workflow,
  completion_finalizer, handoff + energy_usage repos, workspace/layout.
- **Bằng chứng môi trường**: host Windows 11; **Docker khả dụng** (`docker version` → Server 27.5.1,
  Docker Desktop); dự án **đã dùng** Docker read-only mount ở Phase 5 (report §J:
  `docker run --rm -v <repo>:/src:ro python:3.11`, có image digest). ⇒ backend isolation enforce được
  **tồn tại về kỹ thuật**.
- **Governance đã giải quyết**: **ADR-0007 (Accepted, 2026-06-27)** — `docs/product/adr/
  ADR-0007-local-container-isolation-for-test-ant.md` — phê duyệt local Docker isolation (read-only
  mount) riêng cho Test Ant Phase 6, **supersede một phần hẹp** của **ADR-0006** (chỉ phần loại
  container sandbox khỏi MVP, chỉ cho Test Ant). ADR-0006 §Decision dòng 68 / §Follow-up dòng 111 đã
  được thêm cross-reference; các quyết định khác của ADR-0006 giữ nguyên hiệu lực.
- **Gap đã phát hiện**: `CompletionFinalizer` chưa ghi HandoffRecord; `bounded_shell._spawn` không set
  `env=`; `execution/` cố ý chỉ là process-boundary (không phải isolation enforce được).

---

## B. Existing architecture map

Hướng phụ thuộc giữ nguyên: `core/domain` ← `application/ports` ← services/workers/execution/security/
energy ← integration ← workflows (LangGraph chỉ ở `graph.py`) ← cli.

**Tái dùng trực tiếp (frozen):** `CommandPolicy` (validate argv đã-resolve); `SubprocessShellAdapter`
(spawn host-side wrapper `docker run …`, +optional `env`); `OutputLimiter` (redact/truncate **chỉ
stdout/stderr**); `BoundedFileSystemAdapter` (đọc exact-byte để snapshot); `route_retry`/`route_regroup`/
`grant_retry_extension` + `route_after_*`/`apply_approval_delta`/`build_escalation_payload`;
`AttemptOrchestrator` (attempt riêng `{task}-test`); `WorkerExecutionReport`; `WorkerOutcome`;
`DocumentationExecutionPort` (khuôn mẫu `TestExecutionPort`); `EnergyMeasurement`/`ResourceAmount`/
`ResourceKind` (TOKENS/API_CALLS/WALL_TIME/**RETRIES**); `EnergyUsage` repo (idempotent per
worker_run/attempt); `HandoffRecord`/`SqliteHandoffRepository`; `CompletionFinalizer` (chèn terminal
handoff); `ArtifactRoot`; `GraphState` counters; `DecisionGatePolicy`/`GateType`.

**Extension points:** `build_workflow_graph(... test_execution=None)`; node `test` mới; routing
test-specific; terminal handoff trong finalizer; optional `env` cho bounded_shell; constants test.
Thêm node graph ⇒ **bump `WORKFLOW_DEFINITION_VERSION` 3→4**, checkpoint cũ fail-closed.

---

## C. Brainstorming conclusions

C1 Test Ant = worker implementation sau `TestExecutionPort` (`workers/test/`). C2 = **validate-phase
worker**, tách **node `test`** (impure) trước node `validate` (pure). C3 không cần proposal/approval/
write-scope (đọc-only) → `TestExecutionScope` nhẹ. C4 diagnostic hint **deterministic**, không LLM.
C5 energy **tái dùng `EnergyMeasurement`** đa-resource (chi tiết §K, delta). C6 **retry chạy lại đúng
Test Ant** (node test), KHÔNG re-enter DocAnt; attempt mới `{task}-test`; retry_count +1. C7 regroup
**Queen-gated** (REPLAN). C8 hai worker không thay vai. **C9 isolation = enforcement boundary thật**
(§D.4).

---

## D. Phase 6 target architecture

### D.1 Topology (thêm node `test`, bump def 3→4)

```
START → plan → context → decision ─(ALLOW)→ execute(DocAnt) → test(TestAnt) → validate(route) → review → persist(handoff) → END
                          │(REQUIRE_APPROVAL)→ prepare_intent → await_approval ─(interrupt/resume)
                          └(DENY)→ failed
  validate routing (route_after_test_validation):
    pass→review · retryable→TEST(retry_count+1, RE-RUN TestAnt) · regroup→plan|escalate SCOPE_CHANGE
    fatal→failed · escalate→prepare_intent(RETRY_LIMIT|SCOPE_CHANGE→Queen/human)
  terminal nodes → CompletionFinalizer → terminal HandoffRecord (MỌI nhánh)
```

Retry loop = `validate --retryable--> test --> validate`; DocAnt upstream, KHÔNG re-enter. Cancel probe
trước khi chạy test.

### D.2 Luồng Test Ant (node `test`, đọc-only, isolated-enforced)

```
verify identity → load+verify context (exact-byte, manifest digest)
→ resolve command_key → TestCommandProfile (immutable argv + typed targets canonical-in-scope)
→ CommandPolicy.check(inner argv) ── DENY → classify(POLICY_VIOLATION/INVALID_COMMAND) → KHÔNG execute
→ ISOLATION PREFLIGHT: backend.capability() ── UNAVAILABLE → classify(EXECUTION_ISOLATION_UNAVAILABLE) → fail-closed, KHÔNG chạy host
→ build IsolatedExecutionSpec: exact-byte snapshot read-only mount + writable runtime mount + no-network + non-root + limits
→ backend.run(spec) qua SubprocessShellAdapter (host wrapper `docker run …`) [bounded, redact stdout/stderr, audited]
→ classify(exit, process_status, isolation_evidence, transient_reason, deny_reason) → FailureClassification + disposition
→ pre/post canonical digest (defense-in-depth, KHÔNG phải boundary chính)
→ build StructuredTestReport + WorkerExecutionReport(§12) → record EnergyMeasurement (delta) → cleanup container+snapshot (bounded, audit)
→ TestExecutionOutcome(outcome, reason_code, disposition, evidence_refs, attempt_ref)
```

### D.3 Tầng dữ liệu
Intent `TestTask`; Authority `TestExecutionScope` (đọc-only); System `StructuredTestReport` +
`WorkerExecutionReport`; Graph `TestExecutionOutcome` (JSON-safe).

### D.4 Execution isolation — ENFORCEMENT BACKEND (đặt nền CP2)

**Vấn đề với thiết kế temp-copy:** temp-copy + cwd + env + command-allowlist + digest **KHÔNG** chặn
được filesystem authority của code chạy trong test (absolute path, `open()`/`os`/`shutil`, absolute-path
child exe, ghi home/temp, sửa canonical trước khi digest phát hiện). `cwd`/PATH/env chỉ giới hạn
**initial invocation**; digest chỉ là **detection**, không phải **prevention**.

**Backend MVP được chọn (khuyến nghị): local container (Docker) với read-only mount.** Abstraction:

```
TestIsolationPort            # application/ports — graph/worker chỉ thấy port
IsolatedExecutionSpec        # immutable: image, snapshot_mount(ro), writable_mount(rw/tmpfs), inner_argv, env, limits, network
ExecutionIsolationBackend    # adapters — ContainerIsolationBackend (Docker) là impl MVP
IsolationCapability          # preflight: backend khả dụng?  → AVAILABLE | UNAVAILABLE(reason)
```

**Cơ chế enforce (Docker):**
- Snapshot **exact-byte** approved read scope → staging dir → mount **read-only** (`-v snap:/work:ro`).
  Canonical repo & `.git` **không bao giờ** bind-mount (không tồn tại trong namespace container).
- Writable **chỉ** execution-owned runtime mount (`-v out:/out:rw` hoặc tmpfs `--tmpfs /tmp`).
- `--network none` (default, MVP), `--user <non-root>`, `--read-only` rootfs, `--pids-limit`,
  resource limits; child process kế thừa cùng container boundary.
- Timeout → terminate **toàn bộ container** (`docker kill` + `--rm`); cleanup bounded + audit.
- Host wrapper argv `docker run …` do backend dựng **deterministic** (không free-form); inner argv =
  command profile đã validate; `docker` là trusted host executable.

**Invariants (enforced, không chỉ detect):** canonical repo không writable từ test process; `.git`
canonical không expose writable; source/test = exact-byte read-only mount; writable chỉ runtime mount;
child process trong cùng boundary; network disabled mặc định; secret env không truyền vào; non-root
nếu backend hỗ trợ; timeout kill toàn process-tree/container; cleanup bounded+audit; **backend
unavailable → Test Ant fail-closed với `EXECUTION_ISOLATION_UNAVAILABLE`, KHÔNG fallback chạy trực
tiếp trong canonical workspace**; pre/post digest chỉ defense-in-depth.

**Capability/preflight:** `IsolationCapability` kiểm `docker` chạy được (image hiện diện, daemon up).
Default test/E2E cần container → gated như symlink suite Phase 5 (skip khi docker absent, chạy trong
Docker env đã ghi); unit (classifier/report/profile) + fail-closed-path test (fake unavailable backend)
chạy không cần docker.

**Parking lot backend khác:** OS mount-namespace/bubblewrap (Linux), restricted exec identity (POSIX
perms), gVisor/microVM — sau MVP.

### D.5 Materialization (exact-byte, KHÔNG redact source)

- Source/test/config snapshot hoặc read-only mount **giữ nguyên exact bytes** (Test Ant kiểm thử
  implementation thật). **KHÔNG** redact/biến đổi source.
- Trước materialize: validate canonical paths (path policy) + giới hạn **file count + total bytes**;
  loại file ngoài approved read scope (secret loại bởi **scope policy**, không copy-rồi-redact).
- **Snapshot manifest** có per-file digest; invariant: `snapshot_file_digest ==
  approved_canonical_file_digest` trước execution.
- Redaction CHỈ áp dụng cho: stdout/stderr, diagnostic excerpt, audit/evidence/handoff.

### D.6 StructuredTestReport (schema MVP, bounded)
`report_schema_version`, run/attempt/logical_action refs, worker identity, `command_key`/profile
version, `argv_digest` + sanitized argv, test scope/targets, start/end/`duration_ms`, exit_code,
`process_status` ∈ {completed, timeout, interrupted, cancelled, launch_failed, isolation_unavailable,
isolation_setup_failed}, `test_result` ∈ {passed, failed, error, no_tests}, `failure_category`,
`reason_code`, `recovery_disposition`, counts {passed/failed/errors/skipped/xfailed/xpassed |
unavailable}, output truncation/redaction metadata, bounded failure excerpts/evidence refs, diagnostic
hint (bounded), **isolation_result** (clean | snapshot_manifest_digest | mutation_attempt evidence),
`energy_impact_ref`. Parser non-brittle: không parse được → giữ result theo exit/process facts,
counts=unavailable, không bịa số, không ép UNKNOWN nếu exit rõ. Skip/xfail: TestAnt KHÔNG tự thêm;
profile KHÔNG dùng option bỏ test; existing skip/xfail report minh bạch; threshold/baseline dùng config
hiện hữu.

---

## E. Domain model & contracts

| Tên | Module (proposed) | Trách nhiệm / Invariant |
|---|---|---|
| `FailureCategory` | `core/domain/test_failure.py` *(path: preflight CP1)* | TRANSIENT_INTERRUPTION, ADAPTER_TRANSIENT, TEST_DEADLINE_EXCEEDED, EXECUTABLE_MISSING, PERMISSION_DENIED, ADAPTER_CONFIG_INVALID, DETERMINISTIC_TEST_FAILURE, POLICY_VIOLATION, INVALID_COMMAND, EXECUTION_BOUNDARY_FAILURE, ISOLATION_VIOLATION, EXECUTION_ISOLATION_UNAVAILABLE, ISOLATION_SETUP_FAILURE, BUDGET_EXHAUSTED, UNKNOWN |
| `Transience` | cùng module | TRANSIENT / DETERMINISTIC / UNKNOWN (tách khỏi category) |
| `RecoveryDisposition` | cùng module | RETRY / REGROUP_REQUIRED / ESCALATE / TERMINAL_FAILED / TERMINAL_CANCELLED |
| `TestReasonCode` | cùng module | reason ổn định (gồm `TEST_DEADLINE_EXCEEDED`, `EXECUTION_ISOLATION_UNAVAILABLE`) |
| `FailureClassification` | `workers/test/classifier.py` | (category, reason_code, transience, evidence, recommended_disposition) |
| `TestTask` / `TestExecutionScope` | `application/ports/test_worker.py` | intent (command_key+targets) / authority đọc-only (no write field) |
| `TestCommandProfile` + `TestCommandRegistry` | `security/test_command_profile.py` | command_key→argv bất biến + typed targets canonical-in-scope; acceptance vs diagnostic tách |
| `StructuredTestReport` | `workers/test/report.py` | schema §D.6; không output thô/secret/host path |
| `TestFailureClassifier` | `workers/test/classifier.py` | pure/deterministic; không LLM |
| `TestIsolationPort` + `IsolatedExecutionSpec` + `IsolationCapability` | `application/ports/test_isolation.py` | hợp đồng isolation (graph/worker không biết Docker) |
| `ContainerIsolationBackend` | `adapters/container_isolation.py` *(path: preflight CP2)* | impl Docker; dựng `docker run` argv + mount/limit/cleanup |
| `ExecutionSnapshot` | `execution/test_snapshot.py` | materialize exact-byte + manifest digest |
| `TestAnt` | `workers/test/ant.py` | orchestrate D.2; đọc-only; không mutator/write scope |
| `TestExecutionPort` + `TestExecutionOutcome` | `application/ports/test_execution.py` | graph-facing JSON-safe |
| `DurableTestExecution` | `integration/test_execution_adapter.py` | lắp scope, gọi TestAnt, persist report/evidence/energy, settle attempt |
| `TerminalHandoffAssembler` | `application/services/terminal_handoff.py` | append HandoffRecord + structured envelope cho MỌI terminal (idempotent) |

Tái dùng (không tạo mới): `EnergyMeasurement`/`EnergyUsage`; `HandoffRecord`; `WorkerExecutionReport`;
`SubprocessShellAdapter`/`CommandPolicy`/`OutputLimiter`/`BoundedFileSystemAdapter`. File ≤350 dòng.

---

## F. Decision table (classification → disposition; timeout đã sửa)

> Chỉ RETRY khi **transience=TRANSIENT có evidence**. TestAnt KHÔNG gọi model; retry re-run **Test Ant**.

| FailureCategory | Transience | WorkerOutcome | status | Disposition | New attempt? | Re-run | Provider | Approval | Energy |
|---|---|---|---|---|---|---|---|---|---|
| (pass) | – | SUCCESS | pass | →review/persist | no | – | 0 | no | measure 1×, RETRIES delta=0 |
| TRANSIENT_INTERRUPTION (restart/stale-lease/signal **đã audit**) | TRANSIENT | RETRYABLE_FAILURE | retryable | RETRY ≤ limit | yes | TestAnt | 0 | hết budget→RETRY_LIMIT | +1 attempt, delta=1 |
| ADAPTER_TRANSIENT (resource temporarily unavailable, allowlisted) | TRANSIENT | RETRYABLE_FAILURE | retryable | RETRY ≤ limit | yes | TestAnt | 0 | hết budget→RETRY_LIMIT | delta=1 |
| **TEST_DEADLINE_EXCEEDED** (plain timeout, KHÔNG transient evidence) | UNKNOWN | ESCALATION | escalate | **ESCALATE / REGROUP_REQUIRED** (Queen đổi profile/budget — KHÔNG retry same strategy) | no | – (regroup nếu REPLAN) | 0 | yes Queen | ghi escalation |
| ADAPTER_CONFIG_INVALID | DETERMINISTIC | PERMANENT_FAILURE | fatal | TERMINAL_FAILED | no | – | 0 | no | 0 |
| EXECUTABLE_MISSING | DETERMINISTIC | PERMANENT_FAILURE | fatal | TERMINAL_FAILED | no | – | 0 | no | 0 |
| PERMISSION_DENIED | DETERMINISTIC | PERMANENT_FAILURE | fatal | TERMINAL_FAILED | no | – | 0 | no | 0 |
| DETERMINISTIC_TEST_FAILURE | DETERMINISTIC | ESCALATION | escalate | ESCALATE SCOPE_CHANGE→Queen | no | regroup nếu REPLAN | 0 | yes Queen | ghi escalation |
| POLICY_VIOLATION / INVALID_COMMAND / EXECUTION_BOUNDARY_FAILURE | DETERMINISTIC | PERMANENT_FAILURE | fatal | TERMINAL_FAILED | no | – | 0 | no | 0 (không execute) |
| ISOLATION_VIOLATION (canonical digest đổi) | DETERMINISTIC | PERMANENT_FAILURE | fatal | TERMINAL_FAILED + audit | no | – | 0 | no | ghi isolation evidence |
| **EXECUTION_ISOLATION_UNAVAILABLE** / ISOLATION_SETUP_FAILURE | DETERMINISTIC | ESCALATION/PERMANENT | escalate/fatal | **fail-closed**: ESCALATE (env) — KHÔNG retry mù, KHÔNG host fallback | no | – | 0 | yes | ghi evidence |
| BUDGET_EXHAUSTED | DETERMINISTIC | ESCALATION | escalate | ESCALATE gate | no | – | 0 | yes | ghi budget |
| UNKNOWN | UNKNOWN | ESCALATION | escalate | safe ESCALATE (không retry) | no | – | 0 | yes | ghi UNKNOWN |

**Quy tắc (deterministic):** RETRY chỉ cho TRANSIENT_INTERRUPTION/ADAPTER_TRANSIENT (có audit/allowlist
reason). **Plain deadline exceeded KHÔNG retry same strategy** → escalate/regroup. Repeated timeout sau
strategy mới → escalate/terminal (không blind retry). EXECUTABLE_MISSING/PERMISSION/CONFIG/POLICY →
deterministic, không retry. UNKNOWN/isolation-unavailable → escalate, không retry mù. Regroup chỉ
Queen-gated (REPLAN).

---

## G. Checkpoint plan (8 CP — count giữ nguyên)

**CP1 — Taxonomy (classification↔disposition) & contracts.** Goal: enum + `FailureClassification` +
`TestTask`/`TestExecutionScope`/`TestExecutionOutcome`/`TestExecutionPort` + `TestIsolationPort`/
`IsolatedExecutionSpec`/`IsolationCapability`. Preflight: module path enum, `_StrEnum` vs `Enum`, reuse
`TestOutcome`. Invariants: category≠transience; disposition exhaustive; scope không write field. Tests:
membership/parse; disposition table §F (EXECUTABLE_MISSING/PERMISSION/TEST_DEADLINE **không** retry);
JSON-safe outcome. Commit `feat(phase6-cp1): test classification, disposition and isolation contracts`.

**CP2 — ENFORCEABLE isolation backend + command profiles + bounded execution.** Goal:
`ContainerIsolationBackend` (Docker read-only mount, no-network, non-root, container-kill timeout,
cleanup) + `ExecutionSnapshot` exact-byte + `TestCommandRegistry` + bounded run qua
`SubprocessShellAdapter(+env)`. Preflight: composition root cấu hình backend/image +
`trusted_executables['docker']`; `IsolationCapability` availability check; bounded_shell thêm optional
`env` (additive); constants (image, mounts, limits, profile argv, schema versions). Invariants: snapshot
exact-byte + manifest digest == canonical; **canonical/`.git` không writable/expose**; writable chỉ
runtime mount; network disabled default; non-root; child trong cùng backend; timeout kill toàn
container; **backend unavailable → fail-closed, KHÔNG host fallback**; cleanup bounded+audit; profile
không free-form argv. Tests (enforcement, không chỉ digest): (1) absolute-path write canonical
source→**denied**; (2) canonical test file→denied; (3) child process sửa canonical→denied; (4) canonical
`.git`→denied/không expose; (5) ghi approved runtime→OK; (6) ghi ngoài writable→denied; (7) canonical
digest bất biến (defense-in-depth); (8) backend unavailable→không unsafe fallback; (9) timeout/cancel
kill toàn process tree/container; (10) network denied theo default profile; profile deny
`-k`/`--ignore`/argv tự do/path ngoài scope; snapshot digest == canonical. Commit
`feat(phase6-cp2): enforceable test isolation backend, snapshot and command profiles`.

**CP3 — Test Ant worker + report + classifier.** Goal: `TestAnt.execute` đọc-only trả report (§D.6) +
classification/disposition. Preflight: context qua `ContextPackageStore`+digest; hint bounded; counts
non-brittle. Invariants: không mutator/write scope (compile-time); `files_changed=()`; classifier
pure/deterministic; report ghi command_key+argv digest+scope+policy decision+isolation_result (không
host path); skip/xfail không tự thêm. Tests: classifier bảng §F — **audited transient interruption→retry;
resource-unavailable→retry; plain deadline→KHÔNG retry; executable missing/permission→terminal; isolation
unavailable/setup-failure→fail-closed; unknown→escalate**; report counts unavailable khi không parse,
không bịa; TestAnt không mutation capability. Commit `feat(phase6-cp3): test ant worker, report and
classifier`.

**CP4 — Recovery wiring: node `test` + retry-đúng-worker.** Goal: `DurableTestExecution` + inject
`test_execution`; node `test` + `route_after_test_validation` (retryable→TEST). Preflight: wiring
node+edges (`execute→test→validate`, `validate--retryable-->test`); `logical_action_id={task}-test`;
bump def 3→4; routing test-specific (không dùng `_VALIDATION_STATUS` DocAnt). Invariants: **retry chỉ
khi classification=transient**; **plain deadline KHÔNG route về test same strategy**; retry re-run
TestAnt KHÔNG re-enter DocAnt; attempt mới; task identity/strategy/context giữ nguyên; retry_count +1;
deterministic không retry; restart reuse attempt settled; def-3 checkpoint fail-closed. Tests:
**transient retry → TestAnt invocation=2, DocAnt=1, provider không tăng, strategy revision không đổi,
logical test action không đổi, attempt id đổi**; plain deadline→escalate/regroup (không tự re-run);
deterministic→escalate; retry hết→RETRY_LIMIT; restart không double; version guard. Commit
`feat(phase6-cp4): wire test ant node with transient-only retry recovery`.

**CP5 — Persistence: report/evidence, energy (delta) & terminal handoff.** Goal: persist report
(evidence envelope versioned) + `EnergyMeasurement` đa-resource (RETRIES **delta**) idempotent +
**terminal handoff mọi outcome**. Preflight: envelope chứa report (bump `EVIDENCE_ENVELOPE_SCHEMA_VERSION`
nếu cần); `EnergyUsage`+`EnergyMeasurement` ghi TOKENS=0/WALL_TIME/RETRIES-delta keyed
worker_run/attempt; `CompletionFinalizer` chèn `TerminalHandoffAssembler` (idempotent CAS, handoff id
deterministic theo run+outcome); **xác nhận `ResourceAmount` chấp nhận amount=0** (đã verify:
`amount<0` raise → 0 hợp lệ; nếu policy đổi → omit + absence semantics). Invariants: **mỗi attempt
RETRIES delta (0 initial, 1 cho retry-created); sum(delta)==retry_count; KHÔNG cumulative-per-attempt;
restart không thêm measurement**; regroup → audit/budget delta (không gán RETRIES); energy không double;
envelope versioned+bounded; **mọi terminal→handoff** (storage fail→fail-closed audit); handoff chứa final
status/last successful phase/worker-action-attempt history/classification+reason/retry-regroup counts/
escalation decision hoặc pending authority/energy ref/evidence refs/recommended next action/cancellation
info; không secret/raw output/host path. Tests: 1 row/attempt; recovery không thêm row; **initial+2
retry → 3 measurements, sum(RETRIES)==2, retry_count==2, restart không đổi tổng**; energy token=0;
terminal handoff cho completed/failed/rejected/cancelled; no-leak. Commit `feat(phase6-cp5): persist test
evidence, delta energy and terminal handoff`.

**CP6 — Hardening: re-verify real containment/restart/cancellation/idempotency.** Goal: re-verify (không
khởi tạo mới) isolation enforcement + restart windows + cancellation + process-tree termination + bounded
loop. Preflight: restart windows test-exec (trước execute / sau process completion trước state commit /
sau attempt record); cancel probe đã ở node test (CP4) re-verify race. Invariants: cancel→CANCELLED +
terminal handoff, không spawn thêm; restart sau completion trước commit→không double attempt/energy;
output bound/redact trước persist; **timeout kill toàn container/process-tree**; canonical digest bất
biến mọi suite. Tests: restart 3 window (sau completion trước commit không double); security re-verify
(absolute-path write denied bởi backend, child-process git-write contained, ghi ngoài writable denied);
cancellation 3 thời điểm + container terminate; bounded (retry/regroup không vượt limit, không infinite).
Commit `test(phase6-cp6): re-verify containment, restart and cancellation`.

**CP7 — Integration + E2E.** Goal: E2E deterministic full loop hai worker. Preflight: fixture test
target deterministic; deterministic composer DocAnt; container availability gate. Tests E2E (assertion
bắt buộc): all pass→handoff; deterministic fail→escalate Queen→REPLAN regroup→pass→handoff; **transient→
retry: DocAnt invocation=1, TestAnt invocation>1, provider không tăng, canonical repository digest không
đổi**; **test code biết absolute canonical path → write bị isolation backend từ chối → canonical digest
không đổi**; **plain timeout → Test Ant invocation KHÔNG tự tăng → escalation/regroup decision**; retry
hết→escalate; restart giữa loop→resume không trùng; cancel→terminal handoff; **mọi terminal failure có
handoff**. Commit `test(phase6-cp7): end-to-end two-worker scenario matrix`.

**CP8 — Closure audit & completion report.** ROADMAP Phase 6→COMPLETED (status line) + §14; completion
report convention Phase 5 §A–P. Không COMPLETED trước evidence đầy đủ. Commit `docs(phase6): completion
report` → `docs(roadmap): mark phase 6 complete`.

---

## H. Scenario / test matrix

1 all pass→handoff (CP3/7) · 2 deterministic fail→escalate (CP3/4) · 3 **transient retry đúng TestAnt:
TestAnt=2,DocAnt=1,provider không tăng,attempt id đổi** (CP4/7) · 4 adapter transient→bounded retry
(CP4) · 5 retry hết→RETRY_LIMIT (CP4) · 6 regroup Queen REPLAN (CP4/7) · 7 regroup hết→escalate (CP4) ·
8 **plain deadline→KHÔNG retry, escalate/regroup** (CP3/4/7) · 9 **executable missing/permission→terminal,
không retry** (CP3) · 10 invalid/disallowed command→không execute (CP2) · 11 **profile không cho thu hẹp
suite (`-k`/`--ignore`/argv tự do)→DENY** (CP2) · 12 shell chaining→chặn (CP2) · 13 output vượt→truncate/
redact + report (CP2) · 14 timeout→kill container/process-tree (CP2/6) · 15 **absolute-path write canonical
source→denied bởi backend** (CP2/7) · 16 canonical test file write→denied (CP2) · 17 canonical `.git`→
denied/không expose (CP2) · 18 **child-process Git write→contained bởi isolation** (CP2/6) · 19 ghi ngoài
writable→denied (CP2) · 20 runtime artifact chỉ trong runtime mount + cleanup (CP2/6) · 21 cancel 3 thời
điểm→CANCELLED+handoff (CP6) · 22 restart sau completion trước commit→không double energy (CP6) · 23
resume không trùng side effect (CP4/6) · 24 DocAnt đúng contract (CP7) · 25 TestAnt đúng contract đọc-only
(CP3/6) · 26 full loop hai worker (CP7) · 27 escalation Queen (CP4/7) · 28 escalation human RetryGrant
(CP4/7) · 29 budget exhausted (CP4) · 30 unknown→safe escalation (CP3/4) · 31 **mọi terminal→handoff**
(CP5/7) · 32 isolation violation→ISOLATION_VIOLATION+audit (CP2/5) · 33 **isolation backend unavailable→
fail-closed, không host fallback** (CP2/3) · 34 network denied default profile (CP2) · 35 **snapshot digest
== canonical digest trước execution** (CP2).

---

## I. Requirement traceability (bổ sung)

Đầy đủ như các vòng trước, thêm: **Isolation enforcement** → `TestIsolationPort`/
`ContainerIsolationBackend` → CP2 → 15-20,33,34 → enforcement tests → DoD no-mutation; **Exact-byte
snapshot** → `ExecutionSnapshot` → CP2 → 35 → manifest digest; **Transient-only retry** →
classifier+`route_after_test_validation` → CP3/4 → 3,8 → invocation-count + deadline tests; **Energy
delta** → `EnergyMeasurement` → CP5 → 22 → sum delta test; **Terminal handoff** → `TerminalHandoffAssembler`
→ CP5 → 31 → handoff schema; **Fail-closed isolation** → `IsolationCapability` → CP2/3 → 33. Không
requirement nào thiếu test/evidence.

---

## J. Security & role-boundary audit

1. **Isolation backend (OS/container) là boundary chính**: canonical repo & `.git` không bind-mount
   writable → process không có authority ghi canonical kể cả qua absolute path / library / direct `.git`
   write. Child process trong cùng container.
2. **Command allowlist**: chỉ bảo vệ **initial command selection** (profile→argv validated). **KHÔNG**
   dựa PATH để tuyên bố child-process không Git-write — boundary là isolation, không phải PATH.
3. **Exact-byte snapshot** read-only; secret loại bởi scope policy (không copy-redact source).
4. **No-leak**: redact chỉ stdout/stderr/excerpt/audit/handoff.
5. **Fail-closed**: backend unavailable → không chạy host; classified evidence.
6. Compile-time: TestAnt không mutator/write scope. Report system-derived (không provider).

---

## K. Energy & bounded-loop (đã sửa overcount)

- Reuse `EnergyMeasurement(amounts=(WALL_TIME=duration_ms, RETRIES=**delta**, [TOKENS=0, API_CALLS=0]),
  status=MEASURED)`, `ActionKind.TOOL_EXECUTION`; persist `EnergyUsage` keyed worker_run/attempt.
- **RETRIES delta per-attempt**: 0 cho initial, 1 cho attempt do retry tạo. Cumulative = Σ delta =
  GraphState `retry_count` (KHÔNG lưu cumulative trên từng attempt → tránh overcount 0+1+2=3≠2).
- Regroup → audit/budget delta hiện hữu (không gán RETRIES). Restart/replay cùng attempt → KHÔNG
  measurement mới. TOKENS=0 hợp lệ (`ResourceAmount.amount>=0`); nếu policy đổi → omit + absence
  semantics (verify CP5 preflight).
- Limits: retries=2 (+ext 1), regroups=1; `effective_retry_limit` computed. Bounded loop validate↔test
  bởi retry_count → không infinite (CP6).

---

## L. Documentation & closure
Tạo file này ở planning stage + append-only deviation note mỗi CP; CP8 completion report. ROADMAP chỉ
đổi ở CP8. **`ADR-0007` (Accepted) đã hoàn tất TRƯỚC CP1 implementation** (governance gate đã qua);
**CP2 triển khai Docker `ContainerIsolationBackend` đúng theo ADR-0007 đã accepted** (read-only mount,
no-network, non-root, fail-closed, không host fallback). Không tái diễn giải ADR-0007 ngoài phạm vi
Test Ant isolation.

---

## M. Parking lot
OS mount-namespace/bubblewrap, restricted exec identity, gVisor/microVM; LLM diagnostic; flaky
quarantine; test selection; per-test energy scoring; config-overridable retry/regroup policy; worker
thứ ba; auto-fix; Git write automation; distributed execution.

---

## N. Final readiness assessment

**READY_WITH_CHECKPOINT_PREFLIGHTS** — blocker governance đã được giải quyết.

**Governance đã chốt (2026-06-27):** Product Owner **phê duyệt phương án A**. **`ADR-0007` (Accepted)**
— `docs/product/adr/ADR-0007-local-container-isolation-for-test-ant.md` — cho phép **local Docker
container isolation (read-only mount) riêng cho Test Ant** trong Phase 6, supersede một phần hẹp của
ADR-0006 (chỉ phần loại container sandbox khỏi MVP, chỉ cho Test Ant; các quyết định khác của ADR-0006
giữ nguyên). **Backend MVP chính thức = local Docker isolation.** **Không còn PO decision nào đang treo.**

**Preflight còn lại (kỹ thuật, theo từng checkpoint):**
- Exact composition/module path (vd `adapters/container_isolation.py`, `core/domain/test_failure.py`).
- Docker capability/image availability check (`IsolationCapability`).
- Image pin/digest.
- Schema/version bump (`WORKFLOW_DEFINITION_VERSION` 3→4, `EVIDENCE_ENVELOPE_SCHEMA_VERSION` nếu cần).
- Wiring details (node `test`, edges, port injection).
- Test environment gating (E2E container-dependent skip có lý do khi Docker absent; production path
  fail-closed).

Các semantics lõi đã chốt trong kiến trúc: retry re-run đúng Test Ant; isolation enforce thật
(ADR-0007); command profile không free-form; classification ↔ disposition (plain timeout không retry);
terminal handoff mọi nhánh; energy delta không overcount. ⇒ sẵn sàng implementation từ CP1.

---

## O. Implementation deviation log (append-only)

### CP1 — Taxonomy, classification/disposition & contracts (đã triển khai)

Deviations nhỏ so với §E, có evidence repository (không đổi thiết kế tổng):

1. **`FailureClassification` đặt ở `core/domain/test_failure.py`, KHÔNG ở `workers/test/classifier.py`.**
   - *Plan expectation* (§E table): `FailureClassification` liệt kê trong `workers/test/classifier.py`.
   - *Repository evidence*: CP1 cấm tạo classifier có I/O (prompt §5); model là pure domain (chỉ enum +
     dataclass + invariant), và import-boundary test (`test_core_domain_is_infra_free`) bắt domain phải
     infra-free. Đặt cạnh enum trong cùng module domain giữ cohesion và pass boundary.
   - *Decision*: model thuần ở domain; `workers/test/classifier.py` (logic I/O) để lại đúng cho **CP3**.
   - *Impact CP sau*: CP3 import `FailureClassification` từ `core.domain.test_failure` thay vì tự định nghĩa.

2. **Thêm module `core/domain/test_failure_policy.py`** cho canonical category→(transience, disposition,
   reason) policy + `default_classification()` + `cancellation_classification()`.
   - *Plan expectation*: §E không nêu module policy riêng.
   - *Repository evidence*: tách giữ `test_failure.py` ≤350 dòng (206) và cho phép exhaustive-mapping test
     (fail khi thêm `FailureCategory` mà thiếu rule). Policy không cần `WorkerOutcome` nên ở được domain.
   - *Impact CP sau*: CP3 classifier dùng `default_classification(category, …)` thay vì nhúng bảng policy.

3. **`worker_outcome_for()` đặt trong `application/ports/test_execution.py`.**
   - *Repository evidence*: mapping disposition→`WorkerOutcome` cần import `WorkerOutcome`
     (`application/ports/worker.py`) nên KHÔNG đặt được ở domain; co-locate với `TestExecutionOutcome`.
   - *Impact CP sau*: CP4 routing dùng `worker_outcome_for(disposition)` (exhaustive; `TERMINAL_CANCELLED`
     raise — cancellation xử lý out-of-band, không route như worker failure).

4. **Cancellation biểu diễn bằng disposition `TERMINAL_CANCELLED` + reason `EXECUTION_CANCELLED`** (qua
   `cancellation_classification()`), KHÔNG thêm một `FailureCategory` cancellation.
   - *Repository evidence*: cancellation không phải "failure"; taxonomy §E chỉ gồm 15 failure category.
     Invariant fail-closed: `TERMINAL_CANCELLED` ⇒ reason `EXECUTION_CANCELLED`, không bao giờ TRANSIENT.
   - *Impact CP sau*: CP4/CP6 map cancel → CANCELLED + terminal handoff, không qua `worker_outcome_for`.

Tuân thủ: 5 file source mới đều ≤350 dòng; mypy strict `src` clean; ruff lint/format clean; 88 test CP1
xanh + full suite 1474 passed/12 skipped (skip là live/container-gated có sẵn). Không Docker/subprocess/
LangGraph/persistence/energy trong CP1. Không sửa ROADMAP. Phase 6 vẫn `NOT_STARTED` cho tới CP8.

### CP2 — Enforceable isolation backend, snapshot & command profiles (đã triển khai)

Deviations nhỏ so với §D.4/§E, có evidence repository (không đổi thiết kế tổng):

1. **Image pin = content-addressable IMAGE ID, KHÔNG phải `repo@sha256:<RepoDigest>`.**
   - *Plan expectation* (§D.4): image pin theo digest dạng `repository@sha256:…`.
   - *Repository evidence*: host dùng **containerd image store** (Docker Desktop 4.38). Trên store này
     `docker image inspect`/`run` chỉ resolve theo **image ID** `sha256:9800957d…` (verified bằng probe);
     `python:3.11` (tag) và `python@sha256:<RepoDigest>` đều trả "No such image". Giá trị Phase 5 ghi là
     image ID (config digest), không phải RepoDigest.
   - *Decision*: `TEST_ISOLATION_IMAGE_ID = sha256:9800957d…` (immutable, content-addressable) dùng cho cả
     capability inspect lẫn run; không auto-pull. Capability fail-closed nếu inspect ID ≠ 0.
   - *Impact CP sau*: CP3/CP7 dùng cùng image ID; nếu chạy trên host khác phải verify/đổi ID (hoặc đổi sang
     RepoDigest nếu store là classic) — ghi ở constants.

2. **Backend gọi Docker qua `ShellAdapter` port (bounded shell), KHÔNG sửa `bounded_shell.py`.**
   - *Plan expectation* (§B): optional thêm `env` cho `bounded_shell`.
   - *Repository evidence*: inner container env truyền bằng `--env KEY=VALUE` argv; host Docker CLI kế thừa
     env tối thiểu của tiến trình cha. Không cần env additive ở bounded_shell → tránh đụng module nhạy cảm
     (giữ mọi test bounded_shell cũ xanh, `subprocess` vẫn confine đúng một nơi).
   - *Impact CP sau*: nếu sau này cần env host tối thiểu hoá cho Docker CLI, vẫn có thể thêm additive ở CP3.

3. **Lifecycle = `docker run --name <unique>` (no `--rm`) + luôn `docker rm -f`.** Đúng khuyến nghị §5
   (kiểm soát timeout/process-tree). `--mount type=bind` (không `-v`) để host path Windows có drive `:`
   không nhập nhằng. Inner command là **file `.py` trong snapshot** (`python <probe>.py`) vì inner argv đi
   qua `CommandPolicy` (metachar/newline bị chặn) — `python -c "multi;line"` không khả thi.

4. **`IsolatedExecutionSpec` (CP1) không có targets/argv → inner command do `command_profile_key` quyết định
   hoàn toàn; acceptance chạy toàn bộ snapshot (không narrowing).** Target validation vẫn test ở profile/
   resolver layer. Truyền targets xuyên port (nếu CP3 cần) có thể là field additive ở CP3 — chưa đụng CP1.

Tuân thủ: 5 file source CP2 đều ≤350 dòng (max 276); mypy strict `src` clean; ruff lint/format clean;
unit/contract CP2 xanh + **Docker enforcement integration 4/4 PASS thật trên host** (work read-only denied,
out writable, rootfs denied, non-root uid, `.git` không mount, network denied, canonical bất biến,
child-process contained, timeout kill container). Backend unavailable → fail-closed (no host fallback).
Không LangGraph/persistence/energy/handoff/Test-Ant-worker trong CP2. Không sửa ROADMAP. Phase 6 vẫn
`NOT_STARTED` cho tới CP8.

### CP3 — Test Ant worker, structured report & classifier (đã triển khai)

Deviations nhỏ so với §D.6/§E/§G, có evidence repository (không đổi thiết kế tổng):

1. **Read-scope verification = exact-byte snapshot + manifest digest (CP2), KHÔNG dùng `ContextPackageStore`.**
   - *Plan expectation* (§G CP3): "context qua `ContextPackageStore`+digest".
   - *Repository evidence*: CP1 `TestExecutionScope` KHÔNG có `context_package_ref`/`manifest_digest` (chỉ
     `canonical_read_scope`). `ContextPackageStore` phục vụ prepared-context của Documentation Ant, không
     phải read-scope của Test Ant. Read-scope được xác thực bằng `ExecutionSnapshotBuilder.build()` +
     `verify()` (per-file SHA-256 + aggregate digest, CP2) — đây chính là anti-TOCTOU verification.
   - *Decision*: TestAnt KHÔNG nhận `ContextPackageStore`; snapshot provisioner build+verify read-scope và
     trả `manifest_digest`. `files_read = canonical_read_scope`. Không phá public contract CP1/CP2.
   - *Impact CP sau*: CP4 lắp một provisioner thật (builder + Docker `snapshot_root`); contract port giữ nguyên.

2. **Report-level `TestResult` (PASSED/FAILED/ERROR/NO_TESTS) là enum mới ở `workers/test/report.py`.**
   - *Plan expectation*: §G CP3 "reuse `TestOutcome`".
   - *Repository evidence*: CP1 `TestOutcome` chỉ có PASSED/FAILED — không biểu diễn được ERROR/NO_TESTS mà
     §D.6 yêu cầu. Tạo enum report-level riêng (đúng case §18 đã liệt kê), không sửa `TestOutcome` (Phase 2).
   - *Impact CP sau*: CP5 persist report dùng `TestResult.value` (string ổn định).

3. **Hai port nhỏ additive cho worker: `TestSnapshotProvisioner` + (optional) `TestOutputReader`.**
   - *Repository evidence*: CP2 `IsolatedExecutionResult` cố ý KHÔNG surface stdout/stderr (output đi ra
     out-mount). Để TestAnt không import builder/Docker cụ thể và không chạm host path, snapshot
     build/verify/cleanup nằm sau `TestSnapshotProvisioner`; counts parse từ output đã bounded/redacted qua
     `TestOutputReader` optional (vắng → counts=`unavailable`, result đứng trên exit/process facts).
   - *Impact CP sau*: CP4 cấp provisioner Docker thật; output reader là hook tuỳ chọn.

4. **`backend_reason` (transient/executable-missing/permission…) là fact allowlisted, không suy từ text.**
   - *Repository evidence*: CP2 result chỉ có `status/exit_code/duration/evidence_refs`; không có reason ổn
     định. Classifier nhận `BackendReason` typed (refine LAUNCH_FAILED/SETUP_FAILED). Vì CP2 chưa surface
     reason, đường transient-retry được CHỨNG MINH ở classifier unit-level (facts injected); TestAnt qua CP2
     map LAUNCH_FAILED→ISOLATION_SETUP_FAILURE (escalate), không bao giờ tự suy transient từ text.
   - *Impact CP sau*: khi backend cấp reason allowlisted, fact-flow đã sẵn cho retry đúng CP1 invariant.

5. **Orchestration order: capability TRƯỚC provision snapshot (fail-closed + tránh materialize thừa).**
   - *Plan expectation* (prompt §2): snapshot (6/7) trước capability (8).
   - *Repository evidence*: nếu backend unavailable thì không nên build snapshot. Đổi sang identity→resolve→
     capability→provision→run→cleanup. Call-order có test khẳng định `["capability","provision","run","cleanup"]`.
   - *Impact CP sau*: không ảnh hưởng contract; CP4 wiring giữ cùng thứ tự.

6. **Cancellation: report `TERMINAL_CANCELLED` nhưng KHÔNG ép qua `worker_outcome_for` (intentionally raises).**
   - Đúng deviation CP1 #4: `TestExecutionResult.cancelled=True`, `outcome=None`, `worker_report=None`;
     report mang đầy đủ facet terminal-cancelled. Workflow CANCELLED out-of-band thuộc CP4/CP6.

7. **Cleanup security-impact override**: cleanup `FAILED_SECURITY_IMPACT` biến một pass thành
   `ISOLATION_VIOLATION` (terminal) — không để isolation resource còn tồn tại thành silent success (§12).
   Plain cleanup failure (idempotent) không đổi kết quả.

8. **Docker TestAnt integration (gated)**: pinned image (python) không chứa pytest → integration test SKIP
   trên host hiện tại (docker/image/pytest-in-image probe). CP2 đã chứng minh enforcement matrix thật; CP3
   chỉ xác nhận wiring + report host-path-free + cleanup. Đúng giới hạn §14 (không pull, không đổi pinning).

Tuân thủ: 7 file source CP3 đều ≤350 dòng (max 273: `report.py`); mypy strict `src` clean (207 files); ruff
lint/format clean; **173 phase6 test pass / 3 skip (Docker-gated)**, full suite **1585 passed / 13 skipped**;
import/security boundary test khẳng định TestAnt không nhận mutator/Git/provider và worker package không
import Docker backend/LangGraph/persistence/energy/subprocess. `files_changed=()`, `provider_invoked=False`.
Không retry/regroup/escalation wiring, không node `test`, không bump definition, không persistence/energy,
không sửa ROADMAP. Phase 6 vẫn `NOT_STARTED` cho tới CP8.

### CP4 — Durable Test Execution, node `test`, retry đúng worker và classified recovery wiring (đã triển khai)

1. **TestExecutionPort.execute() signature đổi từ CP1 plan: bỏ `attempt_ref`, thêm `context_manifest_digest`.**
   - CP1 plan dự tính adapter nhận `attempt_ref` ngoài; CP4 quyết định adapter tự tạo attempt (owned internally).
   - `context_manifest_digest=""` mặc định → backward-compat với legacy mode. Adapter tạo `attempt_id` qua
     `AttemptOrchestrator.before_execute`.

2. **`BackendReason` di chuyển từ `workers/test/classifier.py` lên `application/ports/test_isolation.py`.**
   - CP1 để BackendReason trong worker package nhưng `IsolatedExecutionResult` (port level) cần tham chiếu nó.
   - Giải quyết circular dependency: port không được import worker. Classifier giờ import BackendReason từ port.

3. **`_bind_approval` và `_execute_documentation` tách ra `graph_support.py` (từ graph.py private).**
   - graph.py sau khi thêm ~50 dòng CP4 sẽ vượt 350 nếu giữ hai helper. Di chuyển sang graph_support.py (public).
   - test_phase5_cp6_composition.py và test_phase5_cp6_preparation.py cập nhật import mới (alias giữ tên cũ).

4. **Cancellation trong `DurableTestExecution` không gọi `worker_outcome_for` (raises by design).**
   - Deviation từ CP1 #4: khi `result.cancelled=True`, trả `TestExecutionOutcome` với `TERMINAL_CANCELLED`.
   - `after_execute` KHÔNG được gọi cho out-of-band cancellation.

5. **`new_graph_state()` bổ sung khởi tạo compact test fields (CP4 additive).**
   - 8 fields mới (`test_status`, `test_outcome`, ...) được khởi tạo với `None`/`[]` trong `new_graph_state`.
   - `GRAPH_STATE_SCHEMA_VERSION` không đổi (2) vì fields là additive optional.

6. **Version guard test (version 3 checkpoint) test đúng layer: `check_definition_version(3)` raises.**
   - Application services gọi `check_definition_version` explicitly, không phải `runner.resume()`.
   - Test sử dụng `runner_v4.check_definition_version(3)` thay vì thử resume thật.

Tuân thủ: 7 file source CP4 đều ≤350 dòng (max 333: `graph.py`); mypy `src` clean trên files thay đổi; ruff
lint/format clean; **47 CP4 test pass** (routing 18, invocation 8, context-binding 12, version 9), full suite
**all passed / skipped**; LangGraph chỉ nằm trong graph.py; worker không import Docker/LangGraph/persistence;
graph layer không import Docker backend. Không persist report, không write energy, không handoff terminal,
không sửa CompletionFinalizer, không sửa ROADMAP. `WORKFLOW_DEFINITION_VERSION` 3→4.

### CP5 — Structured test evidence, delta energy, terminal handoff

1. **`TerminalHandoffService` không import `integration.identity` (import boundary).**
   - Spec gợi ý dùng `HandoffIdFactory` callable + lazy import. Import scanner (AST-level) vẫn phát hiện
     lazy import bên trong function body → `test_import_boundary` fail.
   - Fix: Inline SHA-256 `_terminal_handoff_id(run_id, final_outcome)` trong `application/services/terminal_handoff.py`
     bằng cùng thuật toán (`"\x00".join(("terminal_handoff", run_id, final_outcome))`).
   - Đồng nhất: cùng seed → cùng hex digest với `integration.identity.terminal_handoff_id`.

2. **Migration v3 làm các test v2 regression fail (6 tests).**
   - `SqliteDatabaseBootstrapper` bây giờ chạy v2 + v3 → `schema_version == 3`, không còn là 2.
   - `test_migrate_v1_to_v2_is_ready`: Sau v2-only migration, `classify()` trả `CORRUPTED` (thiếu cột v3),
     không phải `READY`. Sửa: chỉ assert `schema_version == 2`, bỏ classify assertion.
   - `test_migration_on_fresh_v2_is_noop`: Bootstrap (→3) + v2 migrator (no-op) → version 3. Assert `== CODE_MAX_VERSION`.
   - `test_migration_rejects_unsupported_version`: v3 đã valid → dùng version 999.
   - `test_public_bootstrap_*`: Assert version `== CODE_MAX_VERSION` (3) thay vì `== 2`.
   - `test_persistence_database::test_newer_version_is_incompatible`: Insert 999 thay vì 3.
   - `test_application_init::test_init_incompatible_schema`: Insert 999 thay vì 3 (đã fix session trước).

3. **`_V2_VERSION = 2` constant đặt giữa imports gây ruff E402.**
   - Fix: Di chuyển `_V2_VERSION` và `_V1_VERSION` xuống sau tất cả imports.

4. **`HandoffIdFactory` type alias và `handoff_id_factory` param đã bỏ.**
   - `TerminalHandoffService.__init__` đơn giản hóa: không nhận `handoff_id_factory`.
   - ID được tính bởi `_terminal_handoff_id()` inline, không cần dependency injection.

Tuân thủ: 5 file source CP5 đều ≤350 dòng (max 258: `terminal_handoff.py`); mypy `src` clean (213 files);
ruff lint/format clean; **40 CP5 tests pass** (evidence 15, energy 6, handoff 10, recovery 9); full suite
**1672 passed / 15 skipped / 0 failed**; không persist raw output/traceback/path/secret; delta energy RETRIES=0/1;
idempotent handoff by deterministic SHA-256 id; fail-closed on serialization/version error.
