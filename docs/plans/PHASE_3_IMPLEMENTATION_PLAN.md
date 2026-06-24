# Phase 3 — Execution Boundary, Context Package & Energy Enforcement (PLAN, rev.2)

> **Context.** Phase 2 đã `COMPLETED` và merge vào `develop` (`9bc05cc`, working tree sạch).
> ROADMAP §7: execution boundary (Phase 3) phải hoàn tất **trước** worker thật (Phase 5/6). Phase 3
> = 3 cơ chế bảo vệ kiểm thử tự động được: (3A) Execution Boundary, (3B) Context Package + manifest,
> (3C) Energy enforcement. Đây là tài liệu **kế hoạch** — không phải production/test code. Khi
> triển khai: nhánh `phase/3-execution-boundary`, commit theo từng checkpoint. **Tài liệu này KHÔNG
> tuyên bố Phase 3 hoàn thành.**
>
> **rev.2** áp dụng 6 điều chỉnh kiến trúc đã được PO phê duyệt (xem §C.2 + §B.4). Mọi nội dung đã
> chốt ở rev.1 (baseline, scope 3A/3B/3C, DoD, CP0–CP9, fail-closed, no full-repo fallback, argv
> no-shell, context hard budget, redaction-trước-persist, reservation-trước-side-effect, local-first,
> test matrix, traceability, approval handoff thuộc P3 / resolve+resume thuộc P4, không sandbox/
> semantic/embedding/vector) **được bảo toàn**, kể cả 3 quyết định PO: cloud→PENDING_APPROVAL,
> required-artifact-vượt-budget→PENDING_APPROVAL, hard-runtime-budget→STOP→PENDING_APPROVAL.

---

## A. Baseline Verification

| Mục | Giá trị (read-only) | Khớp |
|---|---|---|
| Branch | `develop` | ✅ |
| HEAD | `9bc05cc3373ad6bd87b3cebcfd038c165d42c7ac` | ✅ |
| Working tree | clean | ✅ |
| Phase 3 (ROADMAP §8) | `NOT_STARTED` | ✅ |

**Đã đọc:** `ROADMAP.md`, `ENERGY_POLICY.md`, `CONTEXT_POLICY.md`, `PROJECT_STRUCTURE.md`,
`PHASE_2_PLAN.md`; source `core/domain/*`, `core/ports/*`, `application/ports/{shell,filesystem,
tool_common,tool_errors,secrets,workspace}.py`, `application/errors.py`, `errors.py`,
`config/{constants,models}.py`, `persistence/schema.py`, `tests/test_import_boundary.py`.
**Sai lệch:** không có.

---

## B. Current Architecture Findings

### B.1 Tái sử dụng (KHÔNG tạo mới)
- Layering + port pattern (`Protocol` + error port-owned rooted `AntError`; frozen dataclass +
  `__post_init__`). Value objects `TokenCount`/`UtcTimestamp`/`Identifier`. DI: `Clock`,`IdGenerator`.
- Tool contract Phase 2: `ShellAdapter`/`ShellRequest`/`ShellResult` (argv, **không** shell=True),
  `FileSystemAdapter`/`File*Request`, `ToolInvocationMetadata`, `ToolKind`. → Phase 3 viết impl enforce.
- Error tool sanitized: `ToolPermissionError`/`ToolTimeoutError`/`ToolNotFoundError`/
  `ToolInvalidRequestError`/`ToolExecutionError` (constructor không nhận message tự do).
- Records+repos: `ExecutionEvidence`(+repo), `EnergyUsage`(+repo), `Approval`(resolve-once)+repo,
  `WorkflowCheckpoint`. Schema SQLite v1 đã có bảng tương ứng.
- Config: typed immutable models + `constants.py` single-source; timeout float validator.

### B.2 Gap cần lấp
- **GAP-1**: `tests/test_import_boundary.py::test_no_real_execution_libraries_in_src` cấm
  `subprocess` toàn `src/`. → Sửa allowlist cho phép `subprocess` **chỉ** ở `execution/bounded_shell.py`.
- **GAP-2**: chưa có phát hiện/redact secret trong *nội dung* (`SecretProvider` là cổng *đọc* secret,
  ngược chiều). → Xây redaction primitive dùng chung, đặt ở `security/redaction/`.
- **GAP-3**: `ShellAdapter`/`FileSystemAdapter` mới là contract → Phase 3 viết impl ở `execution/`.
- **GAP-4**: `ExecutionEvidence` không có trường decision/denied → ghi policy decision/deny + energy
  enforcement vào **audit JSONL** `.ant/logs/` (append-only, redacted); evidence "allow" dùng SQLite repo.
- **GAP-5**: `energy/`, `context/` rỗng. → Xây mới; KHÔNG đụng adapter/workflow.

### B.3 Ý nghĩa `tools/` & import boundary (đối chiếu cho rev.2)
- PROJECT_STRUCTURE §3 mô tả `tools/` = "wrapper tool thực thi (shell/git/test runner, file
  patcher)" → trùng vai trò với `execution/`. §8 cho phép mở rộng cấu trúc **với ADR**, cấm thêm
  layer thừa khi MVP chưa cần.
- `test_import_boundary.py` hiện chỉ ràng buộc `core/domain`, `core/ports`, `application/ports`,
  `application/services`, `config`, `adapters`. Các package mới (`security`,`execution`,`context`,
  `energy`) **chưa** được test boundary → rev.2 bổ sung assertion (xem §F/§G).

### B.4 Tác động foundation của 6 revision
- R1 (`security/`+`execution/` top-level): **mở rộng** danh sách package PROJECT_STRUCTURE → cần 1
  **ADR** (ADR-0006 "security/execution split + subprocess confinement"). Không phải blocker (§8 cho
  phép). `execution/` đảm nhận vai trò bounded-executor; `tools/` giữ nguyên cho tool-wrapper tương
  lai (không dùng trong Phase 3).
- R2–R6: nằm trong `application/ports` + `context/` + `energy/` mới — không đụng doc frozen, không
  cần ADR; tuân thủ typed-contract + file ≤350.

### B.5 Technical debt
- `ADAPTER_CONTRACT.md` (Draft) từng nhắc `context_package` trong request, Phase 2 đã bỏ → Phase 3
  đặt `ContextPackage` ở `context/`, KHÔNG đưa ngược vào `LLMRequest` (giữ adapter provider-neutral).

---

## C. Brainstorming Summary

### C.1 Quyết định nền (giữ từ rev.1)
argv allowlist no-shell; canonical realpath + scope (read/write tách), fail-closed; redaction
primitive dùng chung; audit JSONL (không migration); reservation ledger in-memory + persist usage
thực; output per-stream byte cap + drain + redact-trước-truncate; child kill process-group/tree
best-effort.

### C.2 Sáu revision PO đã phê duyệt (rev.2)
| # | Trước | Sau | Lý do |
|---|---|---|---|
| R1 | `tools/` chứa policy + execution lẫn lộn | tách `security/` (policy thuần) + `execution/` (side-effect) | Tránh god-package; dependency direction rõ; future executor không phình package |
| R2 | manifest có trường `worker` | `ContextConsumer{kind,value}` trung lập | Tránh coupling sớm với worker Phase 5/6 |
| R3 | `RoutingDecision.reason: str` | `RoutingReason` enum (+ reason code cho selection/rejection/enforcement/approval) | Typed contract; business logic không so sánh string |
| R4 | `est = chars/4` hard-coded | `TokenEstimator` Protocol + `CharacterHeuristicEstimator` + `TokenEstimationStrategy` + divisor trong config | Estimator thay thế được; không magic number |
| R5 | JSONL như "lựa chọn audit" | `AuditSink` Protocol (port) + `JsonlAuditSink` = adapter MVP, schema-versioned | Future-proof (SQLite/ColonyMemory/Remote sink sau); policy chỉ phụ thuộc port |
| R6 | EnergyManager ôm 4 capability | tách `measurement/reservation/enforcement/routing` + `manager.py` facade | Tránh god object; pure policy tách mutable ledger |

**Trade-off & phương án loại:** thêm 2 top-level package (R1) đánh đổi "lệch PROJECT_STRUCTURE" lấy
ranh giới trách nhiệm — chấp nhận kèm ADR-0006. R6 đánh đổi "nhiều file nhỏ" lấy SRP + file ≤350 —
chấp nhận, KHÔNG tạo abstraction thừa (enforcement/routing là plain policy object, không Protocol
riêng vì chỉ có 1 impl MVP và được manager gọi nội bộ). Vẫn loại: semantic/embedding/vector,
container sandbox, provider tokenizer, bảng SQLite audit/reservation.

---

## D. Proposed Phase 3 Architecture

### D.1 Module tree (mỗi file ≤ 350 dòng, SRP)
```
src/ant_orchestrator/
├── application/ports/
│   ├── audit.py            # [CP0] AuditSink Protocol + AuditEvent + AuditEventType + PolicyDecision
│   │                       #        + AUDIT_SCHEMA_VERSION
│   ├── context_builder.py  # [CP5] ContextBuilder Protocol + ContextBuildRequest + ContextConsumer
│   │                       #        + ConsumerKind + ContextError taxonomy
│   └── energy.py           # [CP7/8] EnergyManager facade Protocol + EnergyDecision + Route
│                           #        + RoutingReason + RoutingDecision + ResourceKind
│                           #        + ApprovalRequest + ApprovalReason + EnforcementReason + EnergyError
├── security/                       # policy THUẦN logic, KHÔNG side-effect, KHÔNG import execution/
│   ├── redaction/
│   │   ├── patterns.py     # [CP0] SecretPattern enum + compiled regex
│   │   └── redactor.py     # [CP0] Redactor (pure) + RedactionResult + RedactionMark
│   ├── path_policy.py      # [CP1] PathPolicy + PathScope + PathDecision + DenyReason
│   └── command_policy.py   # [CP2] CommandPolicy + CommandDecision + CommandDenyReason
├── execution/                      # implementation CÓ side-effect; dùng policy từ security/
│   ├── output_limit.py     # [CP3] OutputLimiter + TruncatedOutput
│   ├── bounded_shell.py    # [CP3] SubprocessShellAdapter (impl ShellAdapter) — DUY NHẤT dùng subprocess
│   └── bounded_fs.py       # [CP4] BoundedFileSystemAdapter (impl FileSystemAdapter)
├── context/
│   ├── estimator.py        # [CP5] TokenEstimator Protocol + CharacterHeuristicEstimator + TokenEstimationStrategy
│   ├── budget.py           # [CP5] ContextBudget + hard-budget enforcement helpers
│   ├── selection.py        # [CP5] ArtifactRequest + ArtifactRequirement + Selected/Rejected + reasons
│   └── package.py          # [CP6] ContextPackageBuilder + ContextPackage + ContextManifest (immutable)
├── energy/
│   ├── measurement.py      # [CP7] EnergyMeasurement + validation (KHÔNG quyết định routing)
│   ├── reservation.py      # [CP7] ReservationLedger (mutable, single-process) + EnergyReservation + ReservationStatus
│   ├── enforcement.py      # [CP8] EnforcementPolicy (pure) → EnergyDecision (KHÔNG side-effect)
│   ├── routing.py          # [CP8] RoutingPolicy (pure) → RoutingDecision (KHÔNG gọi adapter)
│   └── manager.py          # [CP8] EnergyManager facade: orchestrate; ép reserve-trước-side-effect
└── adapters/
    └── jsonl_audit_sink.py # [CP0] JsonlAuditSink (impl AuditSink → .ant/logs/audit-*.jsonl, redacted, versioned)
```
Test double: `tests/support/fake_audit_sink.py` (in-memory `AuditSink`), `FakeClock`/`SequentialIdGenerator` (đã có ở conftest).

### D.2 Dependency direction (không reverse layer / không cycle)
```
core/domain  ←  application/ports{audit, context_builder, energy}
security/* (pure stdlib re/os.path/pathlib)  ──used by──►  execution/* , context/* , energy/manager
        (security KHÔNG import execution/context/energy/adapters)
execution/* ──► security/* + application/ports{shell,filesystem,tool_*,audit} + config + core
        (subprocess CHỈ trong execution/bounded_shell.py)
context/* ──► security/{redaction,path_policy} + application/ports/{filesystem,audit,context_builder}
        + context/* + config + core      (context dùng FileSystemAdapter PORT, KHÔNG import execution/;
        bounded_fs được INJECT ở composition root → context độc lập executor impl)
energy/{measurement,reservation,enforcement,routing} : pure/stateful nội bộ, KHÔNG adapter/executor
energy/manager ──► energy/{4 component} + application/ports/{energy,audit} + core/ports/repositories
        (manager dùng EnergyUsageRepository/Approval…) ; KHÔNG gọi adapter/model trực tiếp
adapters/jsonl_audit_sink ──► application/ports/audit + core/ports/clock + security/redaction (một chiều)
TẤT CẢ: KHÔNG import workflows/ (P4) hay workers/ (P5/6) ; KHÔNG import provider SDK ngoài adapters/
policy/builder KHÔNG import jsonl_audit_sink trực tiếp (chỉ phụ thuộc AuditSink, inject qua composition)
```

### D.3 Happy path
```
ContextPackageBuilder.build(ContextBuildRequest{task_id, consumer, requests, budget})
  → selection.resolve (security/path_policy scope) → read qua FileSystemAdapter(port) → redactor.redact
  → estimator.estimate (sau redaction) → budget enforce → ContextPackage + ContextManifest(immutable,
    ghi consumer + estimator_strategy/version + redactions + remaining) → audit CONTEXT_BUILD
EnergyManager.reserve(plan) → ALLOW → SubprocessShellAdapter.run (command_policy + timeout +
  output_limit + redact) → ExecutionEvidence(repo) + audit EXECUTION(allow)
  → EnergyManager.consume(actual) → EnergyUsage(repo)
```

### D.4 Failure path (fail-closed)
```
path ngoài scope / command ngoài allowlist → DENY → ToolPermissionError + audit(deny)
timeout → kill process-group → status=TIMEOUT → ToolTimeoutError + audit(timeout)
required artifact > budget → ContextError + manifest.dispatchable=False → PENDING_APPROVAL (R-PO)
energy chạm hard budget runtime → EnergyDecision.STOP → ApprovalRequest(RUNTIME_BUDGET_EXCEEDED)
  → PENDING_APPROVAL (KHÔNG side-effect tiếp)
route đề xuất cloud → EnergyDecision.PENDING_APPROVAL, RoutingReason.CLOUD_REQUIRES_APPROVAL (R-PO)
```

### D.5 Audit flow & Approval handoff
- Mọi decision → `AuditEvent` (sanitized, có `correlation_id`, `schema_version`) → `AuditSink` (port).
  MVP adapter `JsonlAuditSink` ghi 1 dòng JSON/`.ant/logs/audit-<UTC-date>.jsonl` (rotation theo ngày,
  deterministic, KHÔNG logging framework). Tương lai có thể `SQLiteAuditSink`/`ColonyMemoryAuditSink`/
  `RemoteAuditSink` — **Phase 3 KHÔNG implement** (và KHÔNG triển khai Colony Memory).
- **Approval handoff (cho Phase 4)**: `ApprovalRequest` (immutable) = {task_id, action,
  current_budget, required_additional, proposed_route: Route, reason: ApprovalReason,
  alternatives_tried: tuple, consequence, expires_at, correlation_id}. Phase 3 **chỉ tạo request +
  trả `PENDING_APPROVAL`**, KHÔNG resolve, KHÔNG side-effect khi chờ. Phase 4 nối `Approval` entity.

---

## E. Domain & Contract Design

### E.1 Enums (typed, single-source — không free-form string trong business logic)
- `DenyReason`: `OUTSIDE_READ_SCOPE`,`OUTSIDE_WRITE_SCOPE`,`TRAVERSAL`,`SYMLINK_ESCAPE`,`NOT_FOUND`,`NOT_A_FILE`.
- `CommandDenyReason`: `EXECUTABLE_NOT_ALLOWED`,`SHELL_METACHARACTER`,`EMPTY_ARGV`.
- `SecretPattern`: `ENV_ASSIGNMENT`,`PEM_PRIVATE_KEY`,`API_TOKEN`,`BEARER`,`AWS_KEY`,`GENERIC_CREDENTIAL`.
- `AuditEventType`: `PATH_DECISION`,`COMMAND_DECISION`,`EXECUTION`,`OUTPUT_TRUNCATED`,`CONTEXT_BUILD`,
  `ENERGY_RESERVATION`,`ROUTING_DECISION`,`ENERGY_ENFORCEMENT`. `PolicyDecision`: `ALLOW`,`DENY`.
- `ConsumerKind` **(R2)**: `WORKER`,`CAPABILITY`,`PLANNER`,`REVIEWER`,`DETERMINISTIC_TOOL`,`EXECUTION_STAGE`.
- `ArtifactRequirement`: `REQUIRED`,`OPTIONAL`.
- `SelectionReason`: `REQUESTED_REQUIRED`,`REQUESTED_OPTIONAL`. `RejectionReason`: `OUTSIDE_SCOPE`,
  `EXCLUDED`,`BINARY`,`OVERSIZED`,`SECRET_FILE`,`BUDGET_EXCEEDED`.
- `TokenEstimationStrategy` **(R4)**: `CHARACTER_HEURISTIC`.
- `ResourceKind`: `TOKENS`,`API_CALLS`,`WALL_TIME`,`RETRIES`,`HUMAN_APPROVALS`.
- `ReservationStatus`: `RESERVED`,`CONSUMED`,`RELEASED`,`EXPIRED`.
- `Route`: `DETERMINISTIC_TOOL`,`CACHE`,`LOCAL`,`CLOUD`.
- `RoutingReason` **(R3)**: `DETERMINISTIC_AVAILABLE`,`CACHE_HIT`,`LOCAL_CAPABLE`,`LOCAL_UNAVAILABLE`,
  `LOCAL_FAILED`,`CAPABILITY_REQUIREMENT`,`QUALITY_REQUIREMENT`,`BUDGET_INSUFFICIENT`,
  `CLOUD_REQUIRES_APPROVAL`,`RUNTIME_BUDGET_EXCEEDED`,`ROUTE_NOT_ELIGIBLE`.
- `EnergyDecision`: `ALLOW`,`USE_DETERMINISTIC_TOOL`,`USE_CACHE`,`ROUTE_LOCAL`,`ESCALATE_CLOUD`,
  `DOWNGRADE`,`PENDING_APPROVAL`,`REJECT`,`STOP`.
- `EnforcementReason` **(R3)**: `WITHIN_BUDGET`,`RESERVATION_REJECTED`,`RUNTIME_HARD_LIMIT`,
  `CLOUD_NEEDS_APPROVAL`,`DETERMINISTIC_PREFERRED`,`CACHE_PREFERRED`,`DOWNGRADE_TO_LOCAL`.
- `ApprovalReason` **(R3)**: `CLOUD_ROUTE`,`REQUIRED_ARTIFACT_OVER_BUDGET`,`RUNTIME_BUDGET_EXCEEDED`.

### E.2 Value objects / records (frozen, invariants)
- `PathScope(read_roots, write_roots)`, `PathDecision(decision, reason: DenyReason|None, resolved: Path|None)`.
- `CommandDecision(decision, reason: CommandDenyReason|None)`.
- `OutputLimit(max_bytes_per_stream: int)`, `TruncatedOutput(text, truncated: bool, original_bytes)`.
- `BoundedExecutionResult(exit_code, stdout: TruncatedOutput, stderr: TruncatedOutput,
  status: ExecStatus{COMPLETED,TIMEOUT,DENIED}, duration_seconds)`.
- `RedactionResult(text, marks: tuple[RedactionMark])`, `RedactionMark(pattern: SecretPattern, count)`
  — **không** lưu giá trị secret.
- `AuditEvent(schema_version, event_type, correlation_id, created_at, detail: Mapping[str,str],
  decision: PolicyDecision|None)` — `detail` sanitized; business logic dựa enum, không parse detail.
- **`ContextConsumer(kind: ConsumerKind, value: str)`** (R2): `value` non-empty; required cả 2 trường;
  serialize `{kind, value}`. Khác `task_id` (task nào) — consumer = *ai/cái gì* nhận context (role/
  capability), không phải worker entity persisted. Phase 3 chỉ cần kiểu, không worker registry.
- `ArtifactRequest(path, requirement)`, `SelectedArtifact(path, source, est_tokens: TokenCount,
  redactions, truncated, reason: SelectionReason)`, `RejectedArtifact(path, reason: RejectionReason)`.
- `ContextBudget(max_input_tokens, max_files, max_file_tokens, allow_full_file)`.
- `ContextBuildRequest(task_id, consumer: ContextConsumer, requests: tuple[ArtifactRequest],
  excluded: tuple[str], budget: ContextBudget)`.
- **`ContextManifest`** (immutable, R2+R4): `task_id`, `consumer: ContextConsumer`, `selected[]`,
  `rejected[]`, `budget_initial`, `budget_used`, `budget_remaining`, `redactions_applied`,
  `any_truncated`, `estimator_strategy: TokenEstimationStrategy`, `estimator_version: int`,
  `policy_version`, `created_at`, `dispatchable: bool`.
- `ContextPackage(manifest, artifacts)`.
- `EnergyBudget(limits: Mapping[ResourceKind,int])`, `EnergyMeasurement(values: Mapping[ResourceKind,int]
  , status: MEASURED|ESTIMATED)`, `EnergyReservation(id, kind, amount, status, created_at)`.
- **`RoutingDecision(route: Route, eligible: bool, reason: RoutingReason, detail: str|None)`** (R3):
  `detail` optional sanitized debug-only, KHÔNG dùng cho quyết định, không secret/prompt/provider output.
- `EnforcementOutcome(decision: EnergyDecision, reason: EnforcementReason)` (R3).
- `ApprovalRequest(...)` (E.D.5) với `reason: ApprovalReason`.

### E.3 Ports / Protocols
- `AuditSink.write(event: AuditEvent) -> None` (R5).
- **`TokenEstimator`** (R4): `estimate(text: str) -> TokenCount`; `strategy: TokenEstimationStrategy`;
  `version: int`. Impl MVP `CharacterHeuristicEstimator(divisor: int)`: `ceil(len(text)/divisor)`
  (len = code points; empty→0; redaction trước estimate; divisor từ config, validated >0).
- `ContextBuilder.build(request: ContextBuildRequest) -> ContextPackage` (raise `ContextError` khi
  required vượt budget / scope vi phạm, kèm manifest `dispatchable=False`).
- **`EnergyManager` facade** (R6 — một port duy nhất cho caller): `reserve(plan)->EnergyReservation|
  EnforcementOutcome`, `consume(reservation, actual)`, `release(reservation)`,
  `decide(plan)->EnforcementOutcome`, `route(plan)->RoutingDecision`. Phía sau facade: `RoutingPolicy`
  (pure), `EnforcementPolicy` (pure), `ReservationLedger` (mutable), measurement value objects —
  **không** expose ra port riêng (tránh abstraction thừa; chỉ 1 impl MVP).
- Impl `ShellAdapter` (`SubprocessShellAdapter`), `FileSystemAdapter` (`BoundedFileSystemAdapter`) — Protocol Phase 2.

### E.4 Error taxonomy
- Boundary: tái dùng `Tool*Error` (sanitized). `ContextError(AntError)`: `ScopeViolation`,
  `BudgetExceededError`, `ArtifactRejectedError`. `EnergyError(AntError)`: `BudgetExceededError`,
  `ReservationError`. Không nhúng raw secret/output/command.

### E.5 Configuration (constants single-source + typed models)
- `BoundaryConfig`: `allowed_read_paths`,`allowed_write_paths`,`allowed_commands`,
  `max_output_bytes_per_stream`,`command_timeout_seconds`.
- `ContextBudgetConfig`: `max_input_tokens`,`max_files`,`max_file_tokens`,`allow_full_file`,
  **`token_estimation_strategy: TokenEstimationStrategy`**, **`token_divisor: int`** (R4; default
  `TOKEN_ESTIMATION_DEFAULT_DIVISOR = 4`, validated >0; không magic number).
- `EnergyBudgetConfig`: `max_total_tokens`,`max_planning/worker/review/retry_tokens`,
  `retry_policy{...}`, **`allow_auto_cloud=False`** (PO).
- Audit/redaction constant: `AUDIT_SCHEMA_VERSION` (sở hữu bởi `application/ports/audit.py`),
  `REDACTION_REPLACEMENT_MARKER` (sở hữu bởi `security/redaction/redactor.py`),
  `OUTPUT_TRUNCATION_MARKER` (CP3). *CP0 chỉ tạo 2 constant đầu trong module sở hữu — KHÔNG đưa vào
  `config/` vì `application/ports` không được import `config` (import-boundary).*

---

## F. Checkpoint Plan (giữ CP0–CP9; 6 revision hấp thụ vào CP hiện có, không tăng số CP)

**CP0 — Shared primitives: redaction (security) + audit (port+adapter) + config skeleton**
- Tạo: `security/redaction/{__init__,patterns,redactor}.py`, `application/ports/audit.py`,
  `adapters/jsonl_audit_sink.py`, `tests/support/fake_audit_sink.py` (in-memory, R5).
- Sửa: **`tests/test_import_boundary.py`** (thêm assertion `security/` pure; audit sink adapter
  không bị import bởi inner layer). *config skeleton: CP0 không cần config user → constant đặt ở
  module sở hữu (xem §E.5).*
- Symbol: `SecretPattern`,`Redactor`,`RedactionResult`,`RedactionMark`,`AuditSink`,`AuditEvent`,
  `AuditEventType`,`PolicyDecision`,`CorrelationId`,`AUDIT_SCHEMA_VERSION`,`JsonlAuditSink`,`FakeAuditSink`.
- Test: redaction (env/PEM/token/bearer/AWS/generic/binary/false-positive/unicode/multi); audit
  contract (schema version invalid bị reject; detail non-str bị reject); JSONL adapter schema_version
  + redacted + không raw secret + 1 dòng/event; policy chạy với `FakeAuditSink`; import-boundary.
- Gate xanh; file ≤350. Evidence: redaction report + sample audit JSONL (versioned).
- CHƯA: enforce path/command, chưa subprocess. Commit: `feat(security): shared redaction and audit sink port (CP0)`.

**CP1 — Path policy (security)** · Tạo `security/path_policy.py` · `PathPolicy/PathScope/PathDecision/
DenyReason` · Test: allowed/disallowed/`..`/absolute-ngoài/symlink-escape/missing/read≠write/Windows-case
· Commit: `feat(security): canonical path policy (CP1)`.

**CP2 — Command policy (security)** · Tạo `security/command_policy.py` · argv allowlist + reject
metachar, không shell · Test: allowed/disallowed exec, chaining/pipe/redirect/subshell/`sh -c`/argv-lệnh-2
· Commit: `feat(security): argv command allowlist policy (CP2)`.

**CP3 — Bounded executor (execution, subprocess thật)** · Tạo `execution/output_limit.py`,
`execution/bounded_shell.py` · **Sửa `tests/test_import_boundary.py`**: cho phép `subprocess` CHỈ ở
`execution/bounded_shell.py` (GAP-1) · `SubprocessShellAdapter` impl `ShellAdapter`: command_policy +
timeout (kill process-group, status TIMEOUT) + output drain/cap/marker + redact-trước-truncate +
`ExecutionEvidence` + `AuditEvent` · Test: timeout, output <,=,> limit, stdout&stderr, secret stdout/
stderr/exception, evidence/audit không secret · Commit: `feat(execution): bounded subprocess executor with timeout/output/secret guards (CP3)`.

**CP4 — Bounded filesystem (execution)** · Tạo `execution/bounded_fs.py` impl `FileSystemAdapter`
(read/write qua `security/path_policy` + redact khi đọc) · Test: in/out scope, binary/oversized,
secret content redact · Commit: `feat(execution): bounded filesystem adapter (CP4)`.

**CP5 — Context selection + estimator strategy + budget** · Tạo `context/{estimator,budget,selection}.py`
· `TokenEstimator`+`CharacterHeuristicEstimator`+`TokenEstimationStrategy` (R4), `ContextBudget`,
`ArtifactRequest`+reasons; selection dùng `security/path_policy` (không import execution) · Test:
estimator deterministic/injectable/empty/unicode + ghi strategy/version; scope filter; no full-repo;
exact boundary; +1 vượt · Commit: `feat(context): selection, injectable token estimator and budget (CP5)`.

**CP6 — Context package + manifest (consumer-based)** · Tạo `context/package.py` ·
`ContextPackageBuilder`,`ContextPackage`,`ContextManifest` (immutable, `consumer: ContextConsumer`
+ `estimator_strategy/version`, R2+R4) · pipeline: resolve→scope→metadata→reject binary/oversized/
secret-file→read(FileSystemAdapter port)→redact→estimate→select priority→enforce hard budget→build→
manifest→validate · audit `CONTEXT_BUILD` · Test: chỉ selected; required-vượt-budget→`dispatchable=False`
+PENDING_APPROVAL; optional bị loại giữ budget; manifest đúng consumer/reason/redaction/remaining/
estimator; manifest không secret · Commit: `feat(context): immutable consumer-scoped context package and manifest (CP6)`.

**CP7 — Energy measurement + reservation** · Tạo `energy/{measurement,reservation}.py`,
`application/ports/energy.py` (Protocol facade + decision/reason enums + `ApprovalRequest`) ·
`EnergyMeasurement`+validation, `ReservationLedger`(mutable)+`EnergyReservation`+`ReservationStatus`,
`ResourceKind`,`EnergyError` · Test: measurement; reserve ok/reject; release unused; consume actual;
duplicate; actual<reserve & actual>reserve · Commit: `feat(energy): measurement and reservation ledger (CP7)`.

**CP8 — Energy enforcement + routing + manager facade + approval handoff** · Tạo `energy/enforcement.py`
(pure→`EnforcementOutcome`), `energy/routing.py` (pure→`RoutingDecision` với `RoutingReason`, R3),
`energy/manager.py` (facade, R6) · Test: deterministic/cache/local ưu tiên; **cloud→PENDING_APPROVAL +
RoutingReason.CLOUD_REQUIRES_APPROVAL** (PO); downgrade khi thiếu budget; STOP khi chạm hard runtime→
PENDING_APPROVAL; **không gọi adapter trước reservation**; enforcement/routing pure không gọi adapter;
manager delegate đúng component; audit decision path · Commit: `feat(energy): enforcement, routing and approval handoff via manager facade (CP8)`.

**CP9 — Integration/e2e (no real worker) + report + docs** · Tạo `tests/test_phase3_integration.py`
+ energy enforcement test report · ráp context→reserve→bounded exec→audit, chứng minh DoD; bổ sung
import-boundary e2e · Sửa docs §K · Commit: `test(phase3): end-to-end enforcement integration and report (CP9)`.

**Dependencies:** CP0 → {CP1,CP2,CP5,CP7}; CP3←CP1+CP2+CP0; CP4←CP1+CP0; CP6←CP5+CP4+CP0;
CP8←CP7+CP0; CP9←all. Shared-first (CP0) chặn duplicate redaction/audit.

---

## G. Automated Test Matrix

**3A — Boundary** (unit + security regression): allowed/disallowed file · `..` · absolute ngoài ·
symlink escape · missing · read≠write · allowed/disallowed exec · chaining `&&` · pipe/redirect ·
`sh -c`/`bash -c` · argv-lệnh-thứ-2 · timeout dừng thật · output <,=,> limit · stdout&stderr đồng thời ·
secret stdout/stderr/exception · evidence allow/deny · evidence/audit không secret · Windows case.

**3B — Context**: chỉ selected xuất hiện · ngoài scope bị loại · no full-repo fallback · required ·
optional · deterministic ordering · secret filename/content · private key · binary · oversized · exact
budget · +1 vượt · optional bị loại giữ budget · required vượt budget→not-dispatchable/PENDING_APPROVAL
· manifest đúng selected/excluded reason/redaction/remaining · **manifest dùng `ContextConsumer` typed
(R2)** · **manifest ghi `estimator_strategy/version` (R4)** · **estimator inject/thay thế được + char
heuristic deterministic (R4)** · package ≤ hard limit · manifest/log không secret.

**3C — Energy**: measurement · reserve ok/reject · release unused · consume actual · retry ·
deterministic/cache/local ưu tiên · cloud→PENDING_APPROVAL · downgrade khi thiếu budget · pending
approval khi vượt gate · reject khi approval không cho phép · STOP khi chạm hard limit · **không gọi
adapter trước reservation** · không gọi cloud khi policy bắt local · không chỉ-log-mà-chạy-tiếp ·
**routing dùng `RoutingReason` enum, không string (R3)** · **enforcement/routing pure không gọi adapter
(R6)** · **manager delegate đúng component (R6)** · audit trail đúng decision path.

**Cross-cutting (rev.2)**: **application logic chạy với `FakeAuditSink` (R5)** · **`JsonlAuditSink`
schema_version + redaction (R5)** · **import-boundary: security không import execution; context không
import execution; subprocess chỉ trong bounded_shell (R1)**.

Loại test: unit (policy/pure), contract (impl thỏa Protocol P2 + TokenEstimator/AuditSink), integration
(CP9), security regression, import-boundary. Không thêm property-based/dependency mới trừ khi cần.

---

## H. Definition of Done Traceability

| DoD | Component (rev.2) | CP | Test | Evidence |
|---|---|---|---|---|
| Không gửi toàn repo | `context/selection` (no fallback) | CP5/6 | no-full-repo | manifest |
| File ngoài scope không xuất hiện | `security/path_policy`+selection | CP1/6 | outside-scope | manifest+audit |
| Secret loại/che | `security/redaction` | CP0/3/4/6 | secret content/stdout/stderr | redaction report |
| Package không vượt budget | `context/budget`+`estimator`+package | CP5/6 | exact/over | manifest(remaining) |
| Boundary chặn path ngoài | `security/path_policy` | CP1 | traversal/symlink/absolute | path matrix+audit |
| Boundary chặn command ngoài | `security/command_policy` | CP2 | chaining/pipe/sh -c | command matrix+audit |
| Timeout dừng thật | `execution/bounded_shell` | CP3 | timeout kill | execution record |
| Output truncate đúng | `execution/output_limit` | CP3 | <,=,> limit | truncated marker |
| Audit allow & deny | `application/ports/audit`+bounded_shell | CP0/3 | evidence allow/deny | audit JSONL+evidence |
| Audit/log không secret | redaction + `JsonlAuditSink` | CP0/3 | secret-in-exception | redacted JSONL |
| Workflow reject/stop/downgrade/approval khi chạm energy | `energy/{enforcement,routing,manager}` | CP8 | enforcement set | enforcement report |

**Chưa kiểm thử trọn vẹn ở Phase 3 (đánh dấu):** *resolve* approval (approve/reject → resume) thuộc
**Phase 4**; Phase 3 chỉ test việc **phát sinh** `PENDING_APPROVAL`+`ApprovalRequest` + **không
side-effect** khi chờ. Không tuyên bố "đạt" cho resume.

---

## I. Security & Failure Analysis

| Risk | Mức | KN | Mitigation | Test/Evidence | Residual |
|---|---|---|---|---|---|
| Path traversal | Cao | TB | canonical realpath + scope, fail-closed | CP1 | Thấp |
| Symlink escape | Cao | TB | resolve symlink rồi so scope | CP1 | Thấp |
| Shell bypass | Cao | TB | argv allowlist no-shell, reject metachar | CP2 | Thấp |
| Child sống sau timeout | TB | TB | kill process-group/tree best-effort | CP3 | TB Windows (ghi rõ) |
| Output deadlock | TB | TB | drain liên tục 2 stream | CP3 | Thấp |
| Secret leak log/audit/exc | Cao | TB | redact-trước-persist; error không message tự do | CP0/3 | Thấp |
| Redact sau truncate lộ 1 phần | TB | Thấp | đọc buffer(limit+margin)→redact→truncate | CP3 | Thấp |
| Budget estimate sai | TB | TB | estimator strategy + hard cap cuối; manifest ghi strategy/version | CP5/6 | TB (est≠actual) |
| Manifest lệch package | TB | Thấp | manifest sinh từ chính artifacts đã chọn | CP6 | Thấp |
| Side-effect trước reservation | Cao | TB | reserve là gate bắt buộc; manager ép thứ tự | CP8 | Thấp |
| Energy chỉ log không enforce | Cao | TB | EnergyDecision đổi hành vi (STOP/REJECT/PENDING) | CP8 | Thấp |
| Sai dependency direction (R1) | TB | TB | import-boundary test security↛execution, context↛execution | CP0/3/9 | Thấp |
| Audit adapter coupling (R5) | TB | Thấp | policy chỉ phụ thuộc `AuditSink`; inject ở composition | CP0 | Thấp |
| Free-form reason gây policy drift (R3) | TB | TB | RoutingReason/EnforcementReason/ApprovalReason enum | CP8 | Thấp |
| Estimator strategy mismatch (R4) | TB | TB | strategy injectable + ghi vào manifest | CP5/6 | TB |
| Manager thành god object (R6) | TB | TB | tách 4 component; manager chỉ orchestrate; file ≤350 | CP8 + file-size gate | Thấp |
| Routing vô tình gọi cloud | Cao | TB | cloud→PENDING_APPROVAL | CP8 | Thấp |
| Context phình semantic | TB | Thấp | cấm embedding/vector; selection tường minh | review | Thấp |
| Audit quá chi tiết→leak | TB | Thấp | detail chỉ string đã redact | CP0 | Thấp |
| Test mock chính policy cần chứng minh | TB | TB | dùng impl thật + fixture fs/process; mock chỉ AuditSink/clock | review tests | Thấp |

---

## J. Decision Gates

**J.1 PO đã chốt (KHÔNG đưa lại danh sách chờ):** cloud→PENDING_APPROVAL; required-vượt-budget→
PENDING_APPROVAL; hard-runtime-budget→STOP→PENDING_APPROVAL; **+ 6 revision kiến trúc rev.2 (R1–R6)
đã phê duyệt** — đã áp dụng, không hỏi lại.

**J.2 Claude tự quyết (đề xuất, đã ghi):** argv allowlist no-shell; canonical realpath+scope; redaction
chung ở `security/`; audit JSONL không migration; reservation ledger in-memory + persist usage thực;
output per-stream cap redact-trước-truncate drain; child kill process-group best-effort; enforcement/
routing là plain policy object (không Protocol riêng — chỉ 1 impl MVP).

**J.3 Hoãn Phase 4 (không chặn):** resolve approval + resume; bảng SQLite cho audit/reservation
(MVP JSONL/in-memory đủ); ngưỡng budget theo từng worker (lấy từ config).

**Conflict nền tảng mới phát hiện:** chỉ R1 lệch danh sách package PROJECT_STRUCTURE §2 → **ADR-0006**
(§8 cho phép mở rộng), KHÔNG blocker. Không có conflict khác.

---

## K. Documentation Changes

- **ADR-0006** — "Separate security policies from execution boundaries" (tạo ở `docs/product/adr/`,
  hợp thức hóa mở rộng PROJECT_STRUCTURE §8 trước CP0).
- Khi closure: `docs/plans/PHASE_3_COMPLETION_REPORT.md` (gate xanh + test report + audit sample);
  cập nhật `ROADMAP.md` §8 Phase 3 → `COMPLETED` + §14 (commit **tách riêng** theo convention P0–2).
  Không sửa `ENERGY_POLICY.md`/`CONTEXT_POLICY.md`/ADR frozen. **Không** triển khai Colony Memory.

---

## L. Proposed Git Strategy

- Branch `phase/3-execution-boundary` (từ `develop`@`9bc05cc`).
- Commit `docs(plan)` (plan này) + `docs(adr)` (ADR-0006) trước CP0; sau đó CP0→CP9 (message §F, scope
  `security`/`execution`/`context`/`energy`). **Không squash** giữa checkpoint. Closure report + cập
  nhật ROADMAP **tách riêng** khỏi code. Merge vào `develop` sau closure audit độc lập.

---

## M. Final Readiness Verdict

**`READY_FOR_IMPLEMENTATION`**

Sau rev.2: 6 revision đã áp dụng nhất quán xuyên suốt module tree, dependency, contracts (E.1–E.5),
CP0–CP9, test matrix, traceability, risk; không phát sinh blocker nền tảng mới (R1 chỉ cần ADR-0006
theo §8, không chặn); 10 checkpoint giữ nguyên (revision hấp thụ vào CP hiện có); mọi file dự kiến
≤350 dòng (R6 tách energy giúp giữ ngưỡng); không scope creep sang worker/Phase 4/semantic/provider
tokenizer. Resume-approval vẫn thuộc Phase 4 (không tuyên bố đạt).
