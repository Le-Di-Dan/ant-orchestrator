# Phase 1 — Core Domain, Config, Workspace & Minimal State Persistence

> **Context (vì sao có kế hoạch này)**
> Phase 0 đã `COMPLETED` (scaffolding + quality gate, ROADMAP §14 v1.1). ROADMAP §7 quy định *persistence tối thiểu PHẢI có trước workflow*. Phase 1 dựng domain thuần Python + persistence SQLite + workspace `.ant/` + config layer — nền tảng để các phase sau (LangGraph ở Phase 4) có thể dừng/persist/resume.
>
> Đây là **tài liệu kế hoạch** (không phải production code). Việc implement Phase 1 sẽ theo các checkpoint §19 ở nhiệm vụ riêng.

---

## 1. Trạng thái và mục tiêu

- **Trạng thái**: Phase 0 `COMPLETED`; Phase 1 `NOT_STARTED`. Branch `develop`, working tree sạch.
- **Mục tiêu** (ROADMAP §8 Phase 1): domain thuần Python + persistence tối thiểu, tồn tại trước mọi workflow.
- **Ranh giới cốt lõi**: Phase 1 **không** phải workflow engine thu nhỏ. Chỉ gồm: dữ liệu domain + ghi/đọc + lifecycle workspace + config. Không orchestration loop, không gọi model, không retrieval/ranking.

---

## 2. Nguồn sự thật đã khảo sát

| Nguồn | Nội dung liên quan Phase 1 | Ràng buộc rút ra |
|---|---|---|
| `ROADMAP.md` §8 Phase 1 (217–256) | Domain model list; trạng thái workflow gồm approval + terminal; SQLite repository pattern; `ant init` tạo `.ant/`; config `.ant/config.yaml`; DoD CRUD + checkpoint/approval + import boundary | Scope contract chính; config = YAML (đã chốt) |
| `ROADMAP.md` §7 (145–167) | Persistence trước workflow; memory record tối thiểu (P1) trước retrieval (P7) | P1 có record tối thiểu cho cả pheromone và memory; retrieval → P7 |
| `ROADMAP.md` §9 (dòng 541) | Terminal state rõ ràng: **CANCELLED/FAILED/COMPLETED/REJECTED**; task terminal không tự resume | `REJECTED` là **task terminal** (§7.2, D32) |
| `PROJECT_STRUCTURE.md` §3–§7 | Cấu trúc package; layout `.ant/`; naming `TASK-0001`; worker cấm xóa `state.sqlite`/`.git` | Layout `.ant/` cố định; `core/` = lõi điều phối |
| `WORKFLOW_SPEC.md` §15 | Task status: created…cancelled (12 giá trị) | Lifecycle Task base; chưa có transition matrix |
| `WORKFLOW_SPEC.md` §3, §9, §14 | Task Record (`source: human`, `priority: normal`); intake từ CLI/API/Human/UI; worker ghi files/commands/result; handoff fields | Field + nguồn enum cho Task/Evidence/Handoff |
| `MEMORY_AND_PHEROMONE_SPEC.md` §4–§7, §15 | Memory/Pheromone types; `confidence: high/medium`; pheromone `expires_after: "7d"` | confidence = enum định tính; TTL → `expires_at` UTC |
| `TECHNICAL_FOUNDATION.md` §3.7–§3.8 | SQLite local state; `.ant/` per project; Python ≥3.11 | Persistence = SQLite |
| `adr/ADR-0005-sqlite-initial-state.md` | "Thiết kế repository layer để đổi DB"; "Không hardcode SQLite trong core" | Repository port/adapter bắt buộc |
| `adr/ADR-0001..0004` | Python-first; LangGraph/LiteLLM/Ollama là implementation tầng sau | Domain provider-neutral |
| `pyproject.toml` | deps=`typer`; dev=`ruff,mypy,pytest`; mypy strict; line-length 100; py311 | Thêm dep cần lý do mạnh; mypy quét `src scripts` |
| `scripts/quality/gate.py` | Gate = ruff-lint, ruff-format, mypy(`src scripts`), file-size(≤350), pytest | Lệnh chuẩn: `python -m scripts.quality.gate`; code mới phải nằm `src/` |
| `src/ant_orchestrator/` | 12 package rỗng; `cli/main.py` Typer rỗng | Có sẵn `core,config,cli…`; chưa có `application,workspace,persistence` |

**Khoảng trống/mâu thuẫn đã giải quyết**:
1. ROADMAP §8 ghi "Pheromone/event record" nhưng §7 yêu cầu memory record từ P1 → **GĐ-2**.
2. PROJECT_STRUCTURE không có package application/workspace/persistence → **D01–D04**.
3. WORKFLOW_SPEC §15 chỉ một lifecycle Task, không transition matrix → **§7.2 + D28** (chỉ membership).
4. WORKFLOW_SPEC không liệt kê enum WorkerRun → **GĐ-5**.
5. `REJECTED` ở ROADMAP §9 (terminal) không có trong WORKFLOW_SPEC §15 → **D32** (`TaskStatus.rejected`).
6. Một số enum value suy luận một phần (TaskPriority low/high, ConfidenceLevel low) → **GĐ-9** (đánh dấu assumption).

---

## 3. Hiện trạng sau Phase 0

- `src/ant_orchestrator/{api,cli,core,config,workflows,adapters,workers,context,memory,energy,tools}/__init__.py` — rỗng.
- `src/ant_orchestrator/cli/main.py` — Typer app rỗng, `ant --help` chạy; entry `ant = ant_orchestrator.cli.main:main`.
- `scripts/quality/{gate,file_size,constants}.py` — gate hoạt động.
- `tests/` — 5 file test Phase 0 (19 passed). Chưa có domain/DB/workspace runtime code.

---

## 4. Scope (bắt buộc làm)

1. **Core domain** (`core/domain`, `core/ports`): entities + records + value objects + enums + domain errors + repository ports + `Clock`/`IdGenerator`.
2. **Application outbound ports** (`application/ports`): `WorkspaceProvisioner`, `DatabaseBootstrapper`, `DatabaseInspector` (không nằm trong core).
3. **Config layer** (`config/`): typed config (chỉ field P1 tiêu thụ) + YAML safe loader + resolver + validation + errors.
4. **Workspace/Nest** (`workspace/`): `WorkspaceArtifactState` + discovery + atomic staging/provisioning + corruption/format handling + git policy + marker.
5. **SQLite persistence** (`persistence/`): Database lifecycle + `DatabaseState` inspection + schema v1 + migration/version contract + repository implementations.
6. **Application services + CLI** (`application/services`, `application/models`): `NestState` aggregate + `InitNest`/`GetNestStatus`/`ShowResolvedConfig` + CLI mỏng + exit codes.
7. **Import-boundary test (AST)** + dependency matrix.
8. **Closure audit** (CP8 riêng).

---

## 5. Out of Scope (ROADMAP §5/§8 + task §9)

Gọi LLM thật; LiteLLM/provider routing; adapter Claude/OpenAI/Gemini/Ollama; LangGraph; worker spawning/lifecycle; task decomposition; execution dependency graph; scheduler/queue; retry/regroup engine; energy **enforcement** (chỉ lưu record); pheromone/memory **retrieval/ranking/filter DSL** (→P7); FastAPI; background process; remote persistence; multi-user; distributed locking; telemetry; encryption/secret manager; plugin; self-evolving roadmap; **CLI `task create/run/approve/cancel`** (→P4); **transition validation** (chưa có matrix); **Approval→Task orchestration** (→P4, §7.2/Patch4); generic CRUD/filter framework; production in-memory repository; **workspace repair** (sửa dữ liệu malformed); **nested Nest** (cấm — D14); **new-colony-from-fork** (→phase sau).

---

## 6. Giả định (ghi rõ để audit)

- **GĐ-1**: Config = YAML (frozen) → cần dependency `PyYAML`.
- **GĐ-2**: P1 gồm Memory + Pheromone ở mức record persistence (append/read khóa cố định), không retrieval/ranking.
- **GĐ-3**: P1 single-process; không lock/concurrency, chỉ giữ boundary (transaction-per-operation).
- **GĐ-4**: stdlib `sqlite3`, không ORM.
- **GĐ-5**: WorkerRunStatus suy ra tối thiểu (tài liệu không liệt kê).
- **GĐ-6**: Identity = UUID4 qua `IdGenerator` port; display id `TASK-0001` hoãn Phase 4.
- **GĐ-7**: Secret/global-user config = out of scope.
- **GĐ-8**: CLI P1 chỉ `init/status/config show`; persistence kiểm chứng qua test.
- **GĐ-9**: Một số enum value là assumption (đánh dấu ở §7.2): `TaskPriority.low/high` (spec chỉ nêu `normal`); `ConfidenceLevel.low` (spec nêu `high/medium`). CHECK trong schema chỉ tạo khi đã ghi rõ assumption traceability.

---

## 7. Domain vocabulary và state model

### 7.1 Vocabulary

| Khái niệm | Phân loại | Mutability |
|---|---|---|
| `TaskId`, `WorkerRunId`, `CheckpointId`, `ApprovalId`, `EnergyUsageId`, … | Value Object (wrap str) | Immutable |
| `UtcTimestamp` | Value Object (wrap `datetime` UTC) | Immutable |
| `TokenCount` | Value Object | Immutable (≥0) |
| `TaskStatus`, `WorkerRunStatus`, `ApprovalStatus`, `TaskSource`, `TaskPriority`, `PheromoneType`, `MemoryType`, `ConfidenceLevel` | Enum | — |
| `Task` | Entity | Immutable; `with_status(...)` trả bản mới |
| `WorkerRun` | Entity | Immutable; cập nhật trả bản mới |
| `Approval` | Record | **Immutable**; `resolve(...)` trả `Approval` mới (D31); resolve-once enforced ở repository |
| `EnergyUsage`, `WorkflowCheckpoint`, `ExecutionEvidence`, `HandoffRecord`, `PheromoneRecord` | Record | Immutable (append-only) |
| `MemoryRecord` | Record | Immutable; `deprecate()` trả record mới |

> **Mutability model (D07)**: mọi domain object immutable; mọi thay đổi trạng thái trả **bản mới** (`Task.with_status`, `Approval.resolve`, `MemoryRecord.deprecate`). Không mutate in-place. Persistence cập nhật row tương ứng (cùng id) một cách có kiểm soát.

### 7.2 State model (authoritative)

> **Nguyên tắc**: không tạo state để "future-proof". `pending/approved/rejected` thuộc `ApprovalStatus` (pending **không** phải decision → đặt tên `ApprovalStatus`, Patch3). KHÔNG có `WorkflowStatus` độc lập P1. `REJECTED` ở ROADMAP §9 là **task terminal** → `TaskStatus.rejected` (D32).

| Type | Owner | Giá trị | Terminal | Nguồn |
|---|---|---|---|---|
| `TaskStatus` | `Task` | created, classified, planned, split, assigned, running, validating, reviewing, **waiting_for_approval**, blocked, completed, failed, cancelled, **rejected** | completed, failed, cancelled, rejected | WORKFLOW_SPEC §15 + ROADMAP §8/§9 |
| `ApprovalStatus` | `Approval` | pending, approved, rejected | approved, rejected | ROADMAP §8/§9 |
| `WorkerRunStatus` | `WorkerRun` | pending, running, succeeded, failed, cancelled | succeeded, failed, cancelled | **Assumption (GĐ-5)** — WORKFLOW_SPEC §9 mô tả execution, không liệt kê enum |
| `TaskSource` | `Task` | human, cli, api | — | WORKFLOW_SPEC §3 (`source: human`) + §3 intake (CLI, API) |
| `TaskPriority` | `Task` | low, normal, high | — | `normal` từ WORKFLOW_SPEC §3; **low/high = assumption (GĐ-9)** |
| `ConfidenceLevel` | `Pheromone`/`Memory` | low, medium, high | — | `high/medium` từ MEMORY spec §5/§7; **low = assumption (GĐ-9)** |
| `PheromoneType` | `PheromoneRecord` | file_relevance, test_failure, worker_note, risk_signal, next_step, blocked_reason, context_hint | — | MEMORY spec §6 (đủ nguồn) |
| `MemoryType` | `MemoryRecord` | project_fact, technical_decision, coding_convention, architecture_summary, known_issue, successful_pattern, human_preference, risk_note | — | MEMORY spec §4 (đủ nguồn) |

**Ánh xạ ROADMAP §8 → P1**: `WAITING_FOR_APPROVAL`/`APPROVAL_REQUIRED` → `TaskStatus.waiting_for_approval`; `APPROVED`/`REJECTED` (quyết định) → `ApprovalStatus`; `CANCELLED`/`FAILED`/`COMPLETED`/`REJECTED` (task outcome) → `TaskStatus` terminal.

**Approval ↔ Task (Patch4)**: P1 **chỉ** định nghĩa và persist hai trạng thái độc lập `ApprovalStatus.rejected` và `TaskStatus.rejected`. Việc approval rejection khiến Task chuyển sang `rejected` thuộc **workflow/application orchestration Phase 4** — **không** có automatic event, cross-repository transaction hay transition orchestration trong P1.

**Transition validation**: WORKFLOW_SPEC chưa có transition matrix → P1 **chỉ validate membership** (giá trị hợp lệ + invariant non-negative + Approval resolve-once §7.1/D31), **không** validate chuyển trạng thái Task (D28). Matrix định nghĩa ở Phase 4.

### 7.3 Domain inventory đồng bộ persistence + DoD

| Domain type | P1? | Persist? | Repository operations (semantic) | Test | Nguồn |
|---|---|---|---|---|---|
| `Task` | Có | Có | lifecycle: `add, get, update, list` | invariant + round-trip | ROADMAP DoD "CRUD Task" |
| `WorkerRun` | Có | Có | lifecycle: `add, get, update, list_by_task` | round-trip | ROADMAP DoD |
| `EnergyUsage` | Có | Có | `append, get, list_by_task, list_by_worker_run` | round-trip + CHECK + ownership | ROADMAP DoD |
| `WorkflowCheckpoint` | Có | Có | `append, get, get_latest_by_task, list_by_task` | round-trip canonical | ROADMAP DoD |
| `Approval` | Có | Có | `add, resolve, get, list_by_task` | resolve-once invariant | ROADMAP DoD/§9 |
| `ExecutionEvidence` | Có | Có | `append, get, list_by_worker_run` | round-trip | ROADMAP §8 |
| `HandoffRecord` | Có | Có | `append, get, list_by_task` | round-trip | ROADMAP §8 |
| `PheromoneRecord` | Có | Có | `append, get, list_by_task` | round-trip | ROADMAP §8 |
| `MemoryRecord` | Có | Có | `append, get, deprecate, list_by_type` | round-trip + deprecate | ROADMAP §7 |

> "CRUD" trong ROADMAP DoD diễn giải = **persist + read back**: Task/WorkerRun có full lifecycle; record append-only chỉ append/read; Memory thêm deprecate; Approval thêm resolve. **Không** delete trong P1. Không generic CRUD/filter DSL.

---

## 8. Brainstorm và phương án (so sánh, có khuyến nghị)

| # | Vấn đề | Phương án | Khuyến nghị | Trade-off |
|---|---|---|---|---|
| 8.1 | Config format | (a) YAML+PyYAML (b) TOML stdlib | (a) | Frozen trong docs; +1 dep nhẹ |
| 8.2 | Persistence | (a) stdlib `sqlite3`+repo (b) SQLAlchemy | (a) | ADR-0005 decouple; ORM over-eng |
| 8.3 | Application layer | (a) package `application/` riêng (b) `core/services` | (a) | Use case tách khỏi domain |
| 8.4 | Provisioning/inspection ports | (a) `application/ports` (b) `core/ports` | (a) | Outbound port ≠ domain contract (D29) |
| 8.5 | ID | (a) UUID4 qua port (b) sequential | (a) | Deterministic test, no race |
| 8.6 | Atomic init | (a) staging dir + rename (b) per-file replace | (a) | All-or-nothing thật |
| 8.7 | Contract test | (a) chạy trên SQLite impl (b) in-memory repo production | (a) | Không production code thừa |
| 8.8 | Nested Nest | (a) cấm mặc định (b) cho phép | (a) | An toàn (D14, PO APPROVED) |
| 8.9 | NestState ownership | (a) split artifact/db + aggregate ở application (b) workspace tự quyết hết | (a) | Workspace không được import sqlite3 (D29/D30) |

---

## 9. Kiến trúc đề xuất (tóm tắt)

```
cli  (composition root: wiring concrete adapters)
 └─> application/services        (InitNest/GetNestStatus/ShowResolvedConfig — điều phối atomic init; TÍNH NestState)
        ├─> application/ports     (WorkspaceProvisioner, DatabaseBootstrapper, DatabaseInspector)   [outbound]
        ├─> application/models    (NestState aggregate, InitNestOutcome, NestStatusView, ResolvedConfigView)
        ├─> core/ports            (repository protocols, Clock, IdGenerator)     [inner persistence boundary]
        ├─> config                (typed config + resolver)
        ├─> workspace    implements WorkspaceProvisioner; tính WorkspaceArtifactState (filesystem/config/marker)
        └─> persistence  implements DatabaseBootstrapper/Inspector + repositories; tính DatabaseState (DB/schema)
                              │
                              ▼
                         core/domain  (entities, records, VO, enum, errors)
```

`workspace` adapter chỉ kiểm filesystem/config/marker → `WorkspaceArtifactState`. `persistence` adapter kiểm database/schema → `DatabaseState`. `application/services` **tổng hợp** thành `NestState` và điều phối atomic init. Workspace **không** import sqlite3 (D29/D30).

---

## 10. Package/module boundaries và dependency matrix

### 10.1 Layout

| Package | File chính | Vai trò |
|---|---|---|
| `errors.py` (top-level neutral) | — | `AntError` base tối thiểu |
| `core/domain/` | `value_objects.py`, `enums.py`, `entities.py`, `records.py`, `errors.py` | Domain thuần |
| `core/ports/` | `repositories.py`, `clock.py`, `ids.py` | Inner persistence boundary (Protocol) |
| `application/ports/` | `workspace.py` (WorkspaceProvisioner, WorkspaceArtifactState, **WorkspacePortError hierarchy**), `database.py` (DatabaseBootstrapper, DatabaseInspector, DatabaseState, **DatabasePortError hierarchy**) | Outbound ports + state enums + port errors (PO APPROVED §5b F1/F2) |
| `application/services/` | `init_nest.py`, `nest_status.py`, `show_config.py` | Use case + NestState aggregate |
| `application/models/` | `nest_state.py` (NestState), `outcomes.py`, `views.py` | DTO/result |
| `application/errors.py` | — | `ApplicationError` |
| `config/` | `models.py`, `loader.py`, `resolver.py`, `constants.py`, `errors.py` | Typed config |
| `workspace/` (mới) | `layout.py`, `discovery.py`, `atomic.py`, `nest.py` | Nest lifecycle (errors owned by `application/ports`) |
| `persistence/` (mới) | `database.py`, `schema.py`, `migrations.py`, `repositories/<entity>.py` | SQLite (errors owned by `application/ports`) |
| `cli/` | `main.py`, `commands/`, `composition.py`, `exit_codes.py` | Delivery + wiring |

> Mỗi file ≤350 dòng (COD-004): repository 1 file/entity; enum/VO/entity/record tách file khi cần.

### 10.2 Dependency matrix (kiểm bằng AST import-boundary test)

| Layer | ĐƯỢC import | TUYỆT ĐỐI KHÔNG import |
|---|---|---|
| `errors.py` | stdlib | mọi package nội bộ |
| `core/domain` | stdlib (`dataclasses,enum,datetime,typing`), `ant_orchestrator.errors` | sqlite3, yaml, typer, langgraph, litellm, provider SDK, config/workspace/persistence/application/cli |
| `core/ports` | `core/domain`, stdlib typing, `errors` | sqlite3/yaml/typer/concrete infra |
| `application/ports` | `core/domain`, stdlib typing, `errors` | sqlite3, yaml, typer, workspace, persistence, langgraph/litellm |
| `application/models` | `core/domain`, stdlib, `errors` | infra cụ thể, typer |
| `application/services` | `core/domain`, `core/ports`, `application/ports` **(bao gồm port errors)**, `application/models`, `config`, `errors` | **`workspace`, `persistence`** (TUYỆT ĐỐI — kiểm bằng AST test), sqlite3, typer |
| `config` | stdlib, `yaml`, `errors` | core/application/workspace/persistence/cli, typer, sqlite3 |
| `workspace` | `application/ports`, `core/domain`, `config`, stdlib, `errors` | **`persistence`, `sqlite3`**, typer, langgraph/litellm |
| `persistence` | `application/ports`, `core/ports`, `core/domain`, `sqlite3`, stdlib, `errors` | typer, yaml, `workspace`, `application/services`, langgraph/litellm |
| `cli` | `application` (services/models), `config`, `workspace`, `persistence`, `typer` | langgraph/litellm/provider |

DoD §21 mục 6: test AST cho `core/domain` + `core/ports` + `application/ports` + **`application/services`** (assert không import `workspace`/`persistence`).

---

## 11. Config design

### 11.1 Phạm vi field (chỉ field P1 tiêu thụ)

```yaml
version: 1            # config DOCUMENT version (khác workspace format & DB schema version)
project:
  name: "<tên project>"   # định danh project, dùng bởi GetNestStatus & ShowResolvedConfig
```

Loại khỏi P1: `default_model`, `local_model`, `test_command`, `lint_command`, `forbidden_paths`, `energy_budget`. **Không định nghĩa field chỉ để lưu/hiển thị.**

### 11.2 Ba loại version tách biệt (D12)

| Khái niệm | Nơi lưu |
|---|---|
| Config document version | `.ant/config.yaml` → `version` |
| Workspace format version | `.ant/workspace.json` (machine marker) |
| SQLite schema version | bảng `schema_migrations` trong `state.sqlite` |

### 11.3 Loader contract (D10)

`yaml.safe_load` bắt buộc; không custom tags; không silent coercion; unknown key reject **mọi cấp**; empty document → `{}` → defaults; invalid root type → `ConfigInvalid`; UTF-8; loader **không** tự rewrite file.

### 11.4 Missing config — ba ngữ cảnh

| Ngữ cảnh | Hành vi |
|---|---|
| A. Init Nest mới (ABSENT) | config chưa có → **tạo default config** |
| B. Workspace CONFIGURED/READY | `config.yaml` thiếu/hỏng → **CORRUPTED** (`NestCorrupted`), KHÔNG defaults âm thầm |
| C. Generic loader gọi với source optional | source absent → defaults |

`ShowResolvedConfig` **phải** kiểm workspace validity trước; CORRUPTED → `NestCorrupted` (không hiển thị defaults).

### 11.5 Errors → `config/errors.py`

`ConfigError(AntError)` → `ConfigInvalid`, `UnknownConfigKey`. **Bỏ `ConfigFileNotFound`** (không use case).

### 11.6 Precedence (D11)

```
built-in defaults  <  project file (.ant/config.yaml)  <  environment (ANT_*)
```
Env override chỉ field string (`ANT_PROJECT_NAME`); `version` không override. **Không** CLI override P1.

---

## 12. Workspace/Nest design

### 12.1 Layout + marker

`.ant/`: `config.yaml`, `workspace.json` (marker), `state.sqlite`, thư mục `tasks/ memory/ pheromones/ logs/ cache/ snapshots/ handoff/`.

`workspace.json` (machine-managed):
```json
{ "workspace_id": "<uuid4>", "workspace_format_version": 1, "created_at": "<UTC ISO-8601>" }
```
Clone repository giữ nguyên `workspace_id`; tạo colony mới từ fork = phase sau.

### 12.2 State model (split owner — Patch1 + Patch2)

**`WorkspaceArtifactState`** (owner: `workspace` adapter — chỉ kiểm filesystem/config/marker):

| Giá trị | Điều kiện |
|---|---|
| `ABSENT` | `.ant/` **hoàn toàn không tồn tại** |
| `CONFIGURED` | `.ant/` tồn tại; `config.yaml` + `workspace.json` tồn tại & hợp lệ |
| `FILES_CORRUPTED` | `.ant/` tồn tại nhưng **thiếu file versioned bắt buộc**, malformed hoặc inconsistent |
| `WORKSPACE_FORMAT_INCOMPATIBLE` | marker hợp lệ cấu trúc nhưng `workspace_format_version` mới hơn application |

**`DatabaseState`** (owner: `persistence` adapter — kiểm `state.sqlite`):

| Giá trị | Điều kiện |
|---|---|
| `MISSING` | `state.sqlite` chưa tồn tại |
| `READY` | DB hợp lệ + `schema_migrations` đầy đủ + bảng/cột bắt buộc đủ |
| `CORRUPTED` | DB tồn tại nhưng malformed / có bảng nhưng thiếu `schema_migrations` / thiếu bảng-cột bắt buộc |
| `SCHEMA_INCOMPATIBLE` | `schema_migrations.version` > application |

**`NestState`** (aggregate, owner: `application/services`, đặt ở `application/models/nest_state.py`):

| WorkspaceArtifactState | DatabaseState | NestState | Lỗi raise | Exit |
|---|---|---|---|---|
| ABSENT | — | `ABSENT` | — (init tạo) | — |
| CONFIGURED | MISSING | `CONFIGURED` | — (init provision) | — |
| CONFIGURED | READY | `READY` | — | — |
| CONFIGURED | CORRUPTED | `CORRUPTED` | `StorageIntegrityError` | **4** |
| CONFIGURED | SCHEMA_INCOMPATIBLE | `INCOMPATIBLE` | `SchemaVersionMismatch` | **4** |
| FILES_CORRUPTED | — | `CORRUPTED` | `NestCorrupted` | **3** |
| WORKSPACE_FORMAT_INCOMPATIBLE | — | `INCOMPATIBLE` | `NestFormatIncompatible` | **3** |

> `.ant/` tồn tại nhưng thiếu config/marker = `FILES_CORRUPTED` (**không** phải ABSENT). DB-origin lỗi → `PersistenceError` (exit 4); workspace-origin lỗi → `WorkspaceError` (exit 3). `NestFormatIncompatible` (workspace) và `SchemaVersionMismatch` (DB) **không** trùng vai trò.

Phân biệt **provisioning** (bootstrap runtime DB còn thiếu) ≠ **repair** (sửa malformed — out of scope).

### 12.3 `ant init` theo NestState

```
ABSENT       → tạo versioned skeleton (config + marker + thư mục) + bootstrap runtime DB → READY   (CREATED)
CONFIGURED   → bootstrap runtime DB (atomic add state.sqlite)                            → READY   (PROVISIONED)
READY        → ALREADY_INITIALIZED, exit 0
CORRUPTED    → WorkspaceError/PersistenceError (theo origin; không tự sửa/xóa)
INCOMPATIBLE → WorkspaceError/PersistenceError (theo origin)
```

### 12.4 Atomic strategy (D16)

**ABSENT** (staging toàn bộ): tạo `.ant.tmp-<uuid>` → ghi config+marker+thư mục → bootstrap DB trong staging → validate → `os.replace(staging, .ant)` → lỗi thì cleanup staging (không để `.ant/` nửa vời).

**CONFIGURED** (provisioning runtime, không đụng file versioned): bootstrap DB vào `.ant/state.sqlite.tmp-<uuid>` → validate → `os.replace(tmp, .ant/state.sqlite)` → lỗi thì xóa tmp, **không** đụng config/marker.

### 12.5 Discovery & edge cases (D13–D17)

| Câu hỏi | Quyết định | Lý do |
|---|---|---|
| `ant init` target | `--path` nếu có, else cwd | Tường minh |
| Chạy từ subdirectory | init tạo tại target; status/config **walk-up** nearest `.ant/` | init explicit |
| Git root làm project root? | **Không** | Không phụ thuộc git |
| **Nested Nest** | **Cấm mặc định** (D14, APPROVED): init phát hiện ancestor có `.ant/` hợp lệ → `NestedNestNotAllowed` | An toàn |
| Nhiều `.ant/` (discovery) | Nearest ancestor | Xác định |
| Symlink | `Path.resolve()` | Nhất quán |
| Discovery tới filesystem root | Dừng → `NestNotFound` | Tránh loop |
| `.ant/` là file | `NestCorrupted` (FILES_CORRUPTED) | Bất biến layout |
| Không permission | `WorkspacePermissionError` → exit 3 | Không nuốt lỗi |
| Staging orphan sau crash | uuid mới → không collision; cleanup hoãn | Đơn giản |

### 12.6 Errors → `workspace/errors.py`

`WorkspaceError(AntError)` → `NestNotFound`, `NestCorrupted`, `NestFormatIncompatible`, `NestedNestNotAllowed`, `WorkspacePermissionError`. (DB schema incompatibility KHÔNG ở đây — thuộc `persistence`.) Outcome init không là exception.

---

## 13. Minimal persistence design

### 13.1 Schema v1 (contract đầy đủ)

Quy ước: `id TEXT` (UUID4); timestamp `TEXT` ISO-8601 UTC; JSON → `TEXT`. `PRAGMA foreign_keys=ON` mỗi connection. FK `ON DELETE RESTRICT`. Enum lưu `TEXT` + CHECK danh sách (chỉ với enum có nguồn/assumption đã ghi).

| Bảng | Cột (type, null, CHECK) | PK | FK | Append/Mutable | Index |
|---|---|---|---|---|---|
| `schema_migrations` | `version INTEGER NN`, `applied_at TEXT NN` | version | — | append-only | — |
| `tasks` | `id TEXT NN`, `title TEXT NN`, `status TEXT NN CHECK∈TaskStatus`, `source TEXT NN CHECK∈TaskSource`, `priority TEXT NN CHECK∈TaskPriority`, `created_at TEXT NN`, `updated_at TEXT NN` | id | — | mutable (status, updated_at) | `idx_tasks_status(status)` |
| `worker_runs` | `id TEXT NN`, `task_id TEXT NN`, `status TEXT NN CHECK∈WorkerRunStatus`, `started_at TEXT NULL`, `finished_at TEXT NULL`, `created_at TEXT NN` | id | task_id→tasks RESTRICT | mutable (status, finished_at) | `idx_wr_task(task_id)` |
| `energy_usage` | `id TEXT NN`, `task_id TEXT NULL`, `worker_run_id TEXT NULL`, `tokens_in INTEGER NN CHECK≥0`, `tokens_out INTEGER NN CHECK≥0`, `created_at TEXT NN`, **CHECK(task_id NOT NULL OR worker_run_id NOT NULL)** | id | task_id→tasks, worker_run_id→worker_runs RESTRICT | append-only | `idx_energy_task(task_id)`, `idx_energy_run(worker_run_id)` |
| `workflow_checkpoints` | `id TEXT NN`, `task_id TEXT NN`, `payload_version INTEGER NN`, `payload_json TEXT NN`, `created_at TEXT NN` | id | task_id→tasks RESTRICT | append-only | `idx_ckpt_task(task_id, created_at)` |
| `approvals` | `id TEXT NN`, `task_id TEXT NN`, `checkpoint_id TEXT NULL`, `status TEXT NN CHECK∈(pending,approved,rejected)`, `reason TEXT NULL`, `requested_at TEXT NN`, `decided_at TEXT NULL`, **CHECK((status='pending' AND decided_at IS NULL) OR (status IN('approved','rejected') AND decided_at IS NOT NULL))** | id | task_id→tasks, checkpoint_id→workflow_checkpoints RESTRICT | mutable (resolve-once) | `idx_appr_task(task_id)` |
| `execution_evidence` | `id TEXT NN`, `worker_run_id TEXT NN`, `files_read_json TEXT NULL`, `files_changed_json TEXT NULL`, `commands_json TEXT NULL`, `result TEXT NULL`, `created_at TEXT NN` | id | worker_run_id→worker_runs RESTRICT | append-only | `idx_evi_run(worker_run_id)` |
| `handoff_records` | `id TEXT NN`, `task_id TEXT NN`, `summary TEXT NN`, `what_changed TEXT NULL`, `next_steps TEXT NULL`, `created_at TEXT NN` | id | task_id→tasks RESTRICT | append-only | `idx_handoff_task(task_id)` |
| `pheromones` | `id TEXT NN`, `task_id TEXT NULL`, `type TEXT NN CHECK∈PheromoneType`, `summary TEXT NN`, `files_json TEXT NULL`, `expires_at TEXT NULL` (UTC), `confidence TEXT NULL CHECK∈(low,medium,high)`, `created_at TEXT NN` | id | task_id→tasks RESTRICT | append-only | `idx_pher_task(task_id)` |
| `memory_records` | `id TEXT NN`, `type TEXT NN CHECK∈MemoryType`, `title TEXT NN`, `summary TEXT NN`, `source TEXT NULL`, `confidence TEXT NULL CHECK∈(low,medium,high)`, `tags_json TEXT NULL`, `created_at TEXT NN`, `deprecated INTEGER NN DEFAULT 0 CHECK∈(0,1)` | id | — | mutable (deprecated) | `idx_mem_type(type)` |

**Notes**: `column approvals.status` (đổi từ `decision`, Patch3). `confidence` enum định tính (không REAL). TTL → `expires_at` UTC (chuyển từ `expires_after: 7d` lúc ghi). `TaskPriority`/`ConfidenceLevel` CHECK gồm giá trị assumption đã ghi GĐ-9. **EnergyUsage ownership (Patch5)**: nếu cả `task_id` và `worker_run_id` cùng có → repository/application validate WorkerRun thuộc đúng Task. P1 không expose delete.

### 13.2 Migration/version + bootstrap contract (D20, D33-liên-quan, Patch7)

Bảng `schema_migrations(version PK, applied_at)`. `CODE_MAX_VERSION = 1` (hằng). **`CREATE TABLE IF NOT EXISTS` KHÔNG được dùng làm bằng chứng schema hợp lệ** — bootstrap phải kiểm trạng thái thực tế:

| Tình huống DB | Hành vi |
|---|---|
| **Hoàn toàn empty** (không bảng nào trong `sqlite_master`) | bootstrap schema v1 trong **một transaction**: tạo bảng → insert version 1 → COMMIT |
| `schema_migrations` tồn tại | validate version + verify bảng/cột bắt buộc; apply migration nếu `version < CODE_MAX` (P1 chỉ v1) |
| Có table nhưng **thiếu `schema_migrations`** | `StorageIntegrityError` |
| `schema_migrations` tồn tại nhưng **thiếu bảng/cột bắt buộc** | `StorageIntegrityError` |
| `version > CODE_MAX` | `SchemaVersionMismatch` (DatabaseState.SCHEMA_INCOMPATIBLE) |
| Mở DB lỗi (malformed file) | `StorageIntegrityError` |
| Migration lỗi giữa chừng | Rollback transaction → DB nguyên trạng |

Connection: `sqlite3.connect`, `check_same_thread=True` (không share connection thread/process); transaction-per-operation (D22). WAL **không** bật P1.

### 13.3 Checkpoint payload contract (D33)

`workflow_checkpoints` lưu **opaque JSON dictionary** + `payload_version`. Canonical serialization: `json.dumps(payload, sort_keys=True, ensure_ascii=False)`; đọc lại `json.loads`. Validation: payload là JSON-serializable dict.

> **Tuyên bố giới hạn (D33)**: persistence boundary cho **canonical serialized representation stable** (cùng input → cùng chuỗi JSON canonical sau round-trip); **resume semantics thuộc Phase 4**. P1 KHÔNG tuyên bố "resume-ready", KHÔNG cam kết byte-identity numeric.

### 13.4 Errors → `persistence/errors.py`

`PersistenceError(AntError)` → `SchemaVersionMismatch`, `RecordNotFound`, `StorageIntegrityError`.

---

## 14. Error model (layer-specific)

| Vị trí | Class |
|---|---|
| `errors.py` (neutral) | `AntError(Exception)` — tối thiểu, không sở hữu infra |
| `core/domain/errors.py` | `DomainError(AntError)` → `InvariantViolation`, `InvalidStatusValue`, `ApprovalAlreadyResolved` |
| `application/errors.py` | `ApplicationError(AntError)` |
| `application/ports/workspace.py` | `WorkspacePortError(AntError)` → `NestNotFound`, `NestCorrupted`, `NestFormatIncompatible`, `NestedNestNotAllowed`, `WorkspacePermissionError` |
| `application/ports/database.py` | `DatabasePortError(AntError)` → `SchemaVersionMismatch`, `StorageIntegrityError`, `RecordNotFound` |
| `config/errors.py` | `ConfigError(AntError)` → `ConfigInvalid`, `UnknownConfigKey` |

Domain **không** sở hữu Config/Workspace/Persistence error. DB lỗi (corruption/schema) → `DatabasePortError` (exit 4); workspace lỗi → `WorkspacePortError` (exit 3). Error ownership thuộc **port boundary** (`application/ports`), không phải adapter — workspace/persistence adapter import errors từ ports (PO directed refactor §5b F2).

---

## 15. CLI/application use cases

### 15.1 Use cases & commands

| Command | Service | Input | Output | Outcome/Result |
|---|---|---|---|---|
| `ant init [--path]` | `InitNestService` | path (default cwd) | thông báo theo outcome | `InitNestOutcome.{CREATED, PROVISIONED, ALREADY_INITIALIZED}` (exit 0); CORRUPTED/INCOMPATIBLE/nested → error |
| `ant status` | `GetNestStatusService` | — | NestState, path, workspace_format_version, schema version | `NestStatusView` |
| `ant config show` | `ShowResolvedConfigService` | — | config resolved + nguồn (sau khi check validity) | `ResolvedConfigView`; CORRUPTED → `NestCorrupted` |

CLI chỉ: parse → gọi service → render `*View`/`Outcome` → map exception sang exit code. Không filesystem/SQLite/domain logic trong handler.

### 15.2 Exit codes (`cli/exit_codes.py`)

| Code | Nghĩa | Exception |
|---|---|---|
| 0 | Thành công (gồm ALREADY_INITIALIZED/PROVISIONED/CREATED) | — |
| 1 | Lỗi không lường trước | `Exception` khác |
| 2 | Config error | `ConfigError` |
| 3 | Workspace error (nested, format-incompatible, files-corrupted, not-found, permission) | `WorkspaceError` |
| 4 | Persistence error (DB corrupted, schema mismatch) | `PersistenceError` |

---

## 16. Decision Register (D01–D33, liên tục)

| ID | Quyết định | Phương án | Khuyến nghị | Lý do/Evidence | PO? |
|---|---|---|---|---|---|
| D01 | Layer layout | (a) như nêu (b) gộp core | (a) | Clean arch; ADR-0005 | Không (đủ evidence) |
| D02 | Package `application/` | (a) riêng (b) core/services | (a) | Use case ≠ domain | Không |
| D03 | Package `workspace/` | (a) riêng (b) config/core | (a) | Filesystem là infra | Không |
| D04 | Package `persistence/` | (a) riêng (b) core | (a) | ADR-0005 | Không |
| D05 | Domain inventory (9 type §7.3) | (a) đúng ROADMAP (b) thêm/bớt | (a) | Bám scope | Không |
| D06 | State ownership: TaskStatus(+rejected) + ApprovalStatus + WorkerRunStatus + TaskSource/Priority + ConfidenceLevel; KHÔNG WorkflowStatus | (a) như nêu (b) WorkflowStatus | (a) | WORKFLOW_SPEC 1 lifecycle | Không |
| D07 | Mutability: immutable, cập nhật trả bản mới (Task.with_status/Approval.resolve/Memory.deprecate) | (a) immutable (b) mutable | (a) | An toàn/test | Không |
| D08 | ID = UUID4 qua `IdGenerator` | (a) UUID (b) sequential | (a) | Deterministic | Không |
| D09 | Datetime: `UtcTimestamp` qua `Clock` | (a) như nêu (b) trực tiếp | (a) | Deterministic | Không |
| D10 | YAML safe loader + strict validation | — | (a) | Frozen YAML | Không (đủ evidence) |
| D11 | Precedence defaults<file<env (không CLI override) | (a) như nêu (b) +CLI | (a) | Chỉ layer có consumer | Không |
| D12 | Tách 3 version | (a) tách (b) gộp | (a) | Khác vòng đời | Không |
| D13 | init target=path/cwd; discovery walk-up | (a) như nêu (b) git root | (a) | Tường minh | Không |
| D14 | **Nested Nest: cấm mặc định** | (a) cấm (b) cho phép | (a) | An toàn | **APPROVED** |
| D15 | Symlink: `Path.resolve()` | (a) resolve (b) giữ | (a) | Nhất quán | Không |
| D16 | Atomic init: staging+rename (ABSENT) / single-file (CONFIGURED) | (a) như nêu (b) per-file | (a) | All-or-nothing | Không |
| D17 | Validity = state model (§12.2) | — | (a) | Phân biệt CONFIGURED/READY | Không |
| D18 | **Git tracking policy `.ant/`** | (a) safety-first §17 (b) track nhiều | (a) | memory/handoff nhạy cảm | **APPROVED** |
| D19 | SQLite schema (10 bảng §13.1, enum CHECK, expires_at, confidence enum) | — | (a) | Đủ DoD, typed | Không |
| D20 | Migration: `schema_migrations`, forward-only | (a) table (b) kv | (a) | Rõ lịch sử | Không |
| D21 | Repository operations semantic (không generic CRUD/delete) | (a) semantic (b) generic | (a) | Tránh DSL | Không |
| D22 | Transaction-per-operation; connection không share thread | — | (a) | An toàn sqlite3 | Không |
| D23 | Error taxonomy layer-specific + `AntError` neutral | (a) layer (b) domain sở hữu | (a) | Tách trách nhiệm | Không |
| D24 | CLI P1: init/status/config show | (a) 3 lệnh (b) +task crud | (a) | task CLI P4 | Không |
| D25 | Exit codes 0/1/2/3/4 | — | (a) | Ổn định | Không |
| D26 | MemoryRecord P1 (record-level) | (a) có (b) hoãn | (a) | ROADMAP §7 | Không |
| D27 | Concurrency/locking out of scope | (a) out (b) lock | (a) | P1 single-process | Không |
| D28 | KHÔNG Task transition validation P1 (chỉ membership) | (a) membership (b) full | (a) | Chưa có matrix | Không |
| D29 | Provisioning/inspection ports ở `application/ports` (không core); workspace không import sqlite3 | (a) application (b) core | (a) | Outbound port ≠ domain | Không |
| D30 | Split state: WorkspaceArtifactState (workspace) + DatabaseState (persistence) + NestState aggregate (application); provisioning ≠ repair | — | (a) | Workspace không kiểm được DB | Không |
| D31 | Approval = immutable, `resolve()` trả bản mới, resolve-once ở repository | (a) immutable resolve (b) append-only | (a) | pending không phải decision | Không |
| D32 | `REJECTED` = `TaskStatus.rejected` (terminal) | (a) task terminal (b) chỉ approval | (a) | ROADMAP §9 | Không (đủ evidence) |
| D33 | Checkpoint payload contract: opaque JSON dict + payload_version + canonical serialization; resume semantics Phase 4 | — | (a) | Tách khỏi D28 | Không |

> Tất cả quyết định đã đủ evidence/APPROVED. PO đã chấp thuận **D14** (cấm nested Nest) và **D18** (git safety policy).

---

## 17. Git tracking policy `.ant/` (D18 — PO APPROVED; safety-first)

| Path | Track? | Lý do |
|---|---|---|
| `config.yaml` | **Track** | user-authored config |
| `workspace.json` | **Track** | marker; `workspace_id` giữ qua clone |
| `tasks/` | **Track** | user-authored task spec (P1 trống → `.gitkeep`) |
| `state.sqlite` / `-wal` / `-shm` | Ignore | runtime DB; provisioned lại bởi `ant init` sau clone (CONFIGURED→READY) |
| `memory/` | Ignore | có thể chứa context/prompt/code nhạy cảm |
| `handoff/` | Ignore | audit artifact có thể chứa context nhạy cảm |
| `pheromones/` | Ignore | short-term TTL |
| `logs/` | Ignore | runtime |
| `cache/` | Ignore | rebuildable |
| `snapshots/` | Ignore | rebuildable |

**`.ant/.gitignore` đề xuất (tạo bởi `ant init`)**:
```gitignore
state.sqlite
state.sqlite-wal
state.sqlite-shm
memory/
pheromones/
handoff/
logs/
cache/
snapshots/
```
(Track: `config.yaml`, `workspace.json`, `tasks/`.) **`ant init` KHÔNG sửa root `.gitignore`.**

> Lifecycle git-clone: clone giữ `config.yaml`+`workspace.json`+`tasks/` → `WorkspaceArtifactState.CONFIGURED` + `DatabaseState.MISSING` → `NestState.CONFIGURED` → `ant init` bootstrap `state.sqlite` → READY.

---

## 18. Test strategy

- **Unit (không mock)**: VO/enum/invariant domain (Approval resolve-once trả bản mới, TaskStatus.rejected terminal, Memory.deprecate trả bản mới); config resolution/precedence/validation; loader negative.
- **Contract test repository**: chạy **trên SQLite implementation** (`tmp_path`/`:memory:`) — KHÔNG in-memory repo production. Protocol compliance kiểm bằng **mypy**.
- **Integration (không mock)**: workspace lifecycle (`tmp_path`); SQLite thật.
- **CLI**: Typer `CliRunner`.
- **Negative**: config invalid/unknown-key(nested)/empty/invalid-root; workspace FILES_CORRUPTED/NestNotFound/file-thay-dir/permission/FORMAT_INCOMPATIBLE/NestedNotAllowed; DB CORRUPTED/SCHEMA_INCOMPATIBLE; ShowConfig trên CORRUPTED → lỗi.
- **NestState aggregate**: bảng §12.2 — mỗi tổ hợp (WorkspaceArtifactState × DatabaseState) → NestState + đúng error/exit.
- **Workspace lifecycle**: ABSENT→CREATED; CONFIGURED(clone: có config+marker, xóa DB)→PROVISIONED; READY→ALREADY_INITIALIZED.
- **SQLite bootstrap (Patch7)**: empty→bootstrap; bootstrap **x2** idempotent + verify integrity; có table thiếu `schema_migrations`→`StorageIntegrityError`; `schema_migrations` thiếu bảng/cột→`StorageIntegrityError`; version>→`SchemaVersionMismatch`; malformed→`StorageIntegrityError`.
- **EnergyUsage**: CHECK(task_id OR worker_run_id); ownership (cả hai → WorkerRun thuộc Task); list_by_task & list_by_worker_run.
- **Approval**: add(pending)→resolve(approved/rejected) trả bản mới; double-resolve → `ApprovalAlreadyResolved`; CHECK status↔decided_at.
- **Atomic**: lỗi staging → không `.ant/`; provisioning lỗi → không đụng config/marker.
- **Determinism**: inject `Clock`+`IdGenerator` fake; env qua dict.
- **Test-only fake**: chỉ khi application service test cần (fake `WorkspaceProvisioner`/`DatabaseBootstrapper`/`DatabaseInspector` qua port).
- **Import-boundary (AST)**: `core/domain`+`core/ports`+`application/ports` infra-free; `workspace` không import `sqlite3`/`persistence`.
- **Path**: `pathlib`; test chạy dev OS (Windows). **KHÔNG** tuyên bố đa nền tảng đã chứng minh.
- **Quality gate**:
  ```bash
  python -m scripts.quality.gate
  # = ruff check . ; ruff format --check . ; mypy src scripts ; python -m scripts.quality.file_size ; pytest
  ```

---

## 19. Kế hoạch checkpoint (CP1–CP8)

> Lệnh kiểm chứng mỗi CP: `python -m scripts.quality.gate`. Dependency graph ở §20.

### CP1 — Domain primitives & state model — **S/M**
1. **Mục tiêu**: VO + state model + ID/datetime + domain errors.
2. **Giá trị**: vocabulary ổn định.
3. **Scope**: VO, enum (TaskStatus+rejected, ApprovalStatus, WorkerRunStatus, TaskSource/Priority, ConfidenceLevel, Pheromone/MemoryType), domain errors, `Clock`/`IdGenerator`.
4. **Files**: `errors.py`; `core/domain/{value_objects,enums,errors}.py`; `core/ports/{clock,ids}.py`.
5. **Public contracts**: enums; `UtcTimestamp`/`*Id`/`TokenCount`; `Clock`/`IdGenerator`; `AntError`/`DomainError`.
6. **Invariants**: enum membership (gồm giá trị assumption GĐ-9); `TokenCount`≥0; UTC; **không transition** (D28).
7. **Tests**: unit VO/enum/invariant.
8. **Acceptance**: gate xanh; domain chỉ import stdlib + neutral errors.
9. **Out of scope**: records, persistence, transition matrix.
10. **Dependency**: Phase 0.
11. **Risk**: thiếu state resume → đối chiếu ROADMAP §9 + §7.2.
12. **Complexity**: S/M.
13. **Review gate**: ✔ chốt enum ownership + assumption.

### CP2 — Domain records, repository ports & application ports — **S/M**
1. **Mục tiêu**: 9 domain type + repository ports (core) + outbound ports (application).
2. **Giá trị**: hợp đồng persistence/provisioning/inspection rõ trước implement.
3. **Scope**: entities `Task`/`WorkerRun`; records (gồm `Approval` immutable resolve, `MemoryRecord` deprecate); `core/ports/repositories.py`; `application/ports/{workspace,database}.py` (`WorkspaceProvisioner`, `DatabaseBootstrapper`, `DatabaseInspector`).
4. **Files**: `core/domain/{entities,records}.py`; `core/ports/repositories.py`; `application/ports/workspace.py`, `database.py`.
5. **Public contracts**: 9 repository Protocol (semantic §7.3, EnergyUsage có list_by_task & list_by_worker_run); 3 outbound port.
6. **Invariants**: Approval resolve trả bản mới; FK logic; ≥0.
7. **Tests**: unit invariant (ApprovalAlreadyResolved, deprecate); mypy Protocol.
8. **Acceptance**: gate xanh; `core`/`application/ports` không import infra.
9. **Out of scope**: implement repo/adapter; services.
10. **Dependency**: CP1.
11. **Risk**: operations lệch DoD → đối chiếu §7.3.
12. **Complexity**: S/M.
13. **Review gate**: ✔ chốt port ownership.

### CP3 — Typed configuration — **M**
1. **Mục tiêu**: đọc/resolve/validate config.
2. **Giá trị**: `ant config show` có dữ liệu thật.
3. **Scope**: models (§11.1), YAML safe loader (§11.3), resolver (§11.6), errors (§11.5). **Thêm `PyYAML`**.
4. **Files**: `config/{models,loader,resolver,constants,errors}.py`.
5. **Public contracts**: `ConfigResolver.resolve(...) -> ResolvedConfig`; config errors.
6. **Invariants**: loader rules; unknown key reject mọi cấp; không coercion.
7. **Tests**: happy + negative (empty/invalid-root/unknown-nested/precedence env>file); env qua dict.
8. **Acceptance**: gate xanh; config không rò vào domain.
9. **Out of scope**: CLI override; model/command fields.
10. **Dependency**: CP1.
11. **Risk**: dep PyYAML — đủ evidence (D10).
12. **Complexity**: M.
13. **Review gate**: —

### CP4 — SQLite foundation, inspection & schema v1 — **M**
1. **Mục tiêu**: connection lifecycle + schema bootstrap (Patch7) + migration/version + `DatabaseState` inspection; implement `DatabaseBootstrapper`/`DatabaseInspector`.
2. **Giá trị**: nền persistence version-safe; báo `DatabaseState` cho aggregate.
3. **Scope**: `Database`, `state.py` (DatabaseState), `schema.py` (DDL §13.1), `migrations.py` (§13.2).
4. **Files**: `persistence/{database,state,schema,migrations,errors}.py`.
5. **Public contracts**: `Database.connect`; `DatabaseBootstrapper.bootstrap`; `DatabaseInspector.classify() -> DatabaseState`.
6. **Invariants**: bootstrap idempotent + transactional + integrity-verified (không tin `IF NOT EXISTS`); foreign_keys ON; CHECK enforced; mismatch→SCHEMA_INCOMPATIBLE.
7. **Tests** (real sqlite tmp): empty→bootstrap; x2 idempotent + integrity; partial (thiếu schema_migrations / thiếu bảng-cột)→`StorageIntegrityError`; version>→`SchemaVersionMismatch`; malformed→`StorageIntegrityError`; rollback; CHECK vi phạm bị chặn.
8. **Acceptance**: gate xanh.
9. **Out of scope**: WAL; repositories.
10. **Dependency**: **CP2** (implements DatabaseBootstrapper/Inspector).
11. **Risk**: integrity-check sai → test partial schema.
12. **Complexity**: M.
13. **Review gate**: ✔ chốt bootstrap states.

### CP5 — Workspace lifecycle — **M**
1. **Mục tiêu**: `WorkspaceArtifactState` + discovery + atomic staging/provisioning + nested-forbid + git policy; implement `WorkspaceProvisioner`.
2. **Giá trị**: `.ant/` tạo/provision/phát hiện an toàn, sống qua git-clone.
3. **Scope**: `state.py` (WorkspaceArtifactState §12.2), layout/marker, discovery (§12.5), atomic (§12.4), `.gitignore` (§17).
4. **Files**: `workspace/{state,layout,discovery,atomic,nest,errors}.py`.
5. **Public contracts**: `WorkspaceProvisioner` (create_staging/publish/provision_db_slot); `classify_artifact() -> WorkspaceArtifactState`; `discover`.
6. **Invariants**: không đụng file versioned khi provisioning; lỗi → không `.ant/` nửa vời; nested cấm; **không import sqlite3** (D29).
7. **Tests** (`tmp_path`): ABSENT/CONFIGURED/FILES_CORRUPTED/FORMAT_INCOMPATIBLE classify; nested→`NestedNestNotAllowed`; discovery walk-up; staging cleanup; `.gitignore` đúng; file-thay-dir/permission.
8. **Acceptance**: gate xanh; snapshot layout khớp §12.1; AST: workspace không import sqlite3/persistence.
9. **Out of scope**: orphan GC; lock; repair; tính DatabaseState/NestState.
10. **Dependency**: **CP3 + CP4** (init ghi config + cần slot DB do CP4 bootstrap; aggregate ở CP7).
11. **Risk**: `os.replace` directory Windows → test riêng.
12. **Complexity**: M.
13. **Review gate**: ✔ chốt atomic + state + git policy.

### CP6 — SQLite repositories — **M/L**
1. **Mục tiêu**: implement repository semantic (§7.3).
2. **Giá trị**: persistence round-trip mọi domain type.
3. **Scope**: 9 repository SQLite; mapping row↔domain; checkpoint canonical JSON (§13.3, D33); Approval resolve; EnergyUsage ownership validate.
4. **Files**: `persistence/repositories/<entity>.py`.
5. **Public contracts**: implement `core/ports.repositories`.
6. **Invariants**: round-trip giữ nguyên; checkpoint canonical-stable; not-found→`RecordNotFound`; CHECK; resolve-once; energy ownership.
7. **Tests**: contract test trên SQLite; round-trip 9 type; deprecate; Approval resolve + double-resolve reject; FK RESTRICT; energy CHECK + ownership + list_by_*; checkpoint canonical-stable.
8. **Acceptance**: gate xanh; DoD §21 mục 2–4 đạt.
9. **Out of scope**: retrieval/ranking/filter DSL.
10. **Dependency**: **CP2 + CP4**.
11. **Risk**: serialization checkpoint → test canonical-stable.
12. **Complexity**: M/L.
13. **Review gate**: ✔.

### CP7 — Application services, NestState & CLI — **M**
1. **Mục tiêu**: tính `NestState` aggregate; điều phối atomic init; CLI mỏng; chốt import boundary.
2. **Giá trị**: `ant init/status/config show` chạy.
3. **Scope**: `NestState` (application/models) tổng hợp WorkspaceArtifactState + DatabaseState (§12.2); services (init điều phối staging→config→DB→validate→publish theo NestState); application models/outcomes/views; CLI + composition + exit codes; import-boundary AST test.
4. **Files**: `application/models/{nest_state,outcomes,views}.py`, `application/services/*`, `application/errors.py`; `cli/{main,composition,exit_codes}.py`, `cli/commands/`; `tests/test_import_boundary.py`.
5. **Public contracts**: `NestState`; 3 service; `InitNestOutcome`; exit-code table §15.2.
6. **Invariants**: CLI không domain/IO logic; init idempotent; provisioning không corrupt config/marker; ShowConfig check validity; DB-origin→PersistenceError(4), workspace-origin→WorkspaceError(3).
7. **Tests**: NestState aggregate matrix (§12.2); Typer `CliRunner` (3 lệnh, exit codes); idempotency; clone→provision; failure-không-corrupt; AST import-boundary.
8. **Acceptance**: gate xanh; DoD §21 mục 1,6,7 đạt.
9. **Out of scope**: task CLI; FastAPI.
10. **Dependency**: **CP3 + CP5 + CP6**.
11. **Risk**: composition root rò domain logic → review gate.
12. **Complexity**: M.
13. **Review gate**: ✔.

### CP8 — Documentation & closure audit — **S** (riêng)
1. **Mục tiêu**: audit độc lập + evidence.
2. **Giá trị**: chứng minh DoD.
3. **Scope**: full gate; đối chiếu DoD §21; soạn `docs/plans/PHASE_1_COMPLETION_REPORT.md`.
4. **Files**: `docs/plans/PHASE_1_COMPLETION_REPORT.md`.
5. **Public contracts**: —.
6. **Invariants**: ROADMAP Phase 1 → COMPLETED **chỉ** trong nhiệm vụ implementation riêng, **sau audit PASS**.
7. **Tests**: toàn bộ gate.
8. **Acceptance**: mọi mục DoD có evidence.
9. **Out of scope**: đổi ROADMAP ở nhiệm vụ trước đó.
10. **Dependency**: CP1–CP7.
11. **Risk**: tuyên bố không kiểm chứng → wording §21.
12. **Complexity**: S.
13. **Review gate**: ✔ closure.

---

## 20. Dependency và sequencing

```
CP1 → CP2
CP1 → CP3
CP2 → CP4
CP3 + CP4 → CP5
CP2 + CP4 → CP6
CP3 + CP5 + CP6 → CP7
CP1–CP7 → CP8
```

- **Dependency mới duy nhất**: `PyYAML` (CP3) — frozen-by-doc.
- Không dependency phase sau.

---

## 21. Definition of Done (auditable)

| # | Tiêu chí | Bằng chứng |
|---|---|---|
| 1 | `ant init`: ABSENT→READY (CREATED); CONFIGURED(clone)→READY (PROVISIONED); READY→ALREADY_INITIALIZED; CORRUPTED/INCOMPATIBLE→error (đúng exit 3/4 theo origin); nested→error | test CP5/CP7 |
| 2 | Task + WorkerRun lifecycle persistence; EnergyUsage append/read (list_by_task & list_by_worker_run, CHECK, ownership) | test CP6 |
| 3 | Checkpoint append/read **canonical-serialized stable**; Approval add/resolve/read (resolve-once, trả bản mới) | test CP6 |
| 4 | ExecutionEvidence/Handoff/Pheromone append/read; Memory append/read/deprecate | test CP6 |
| 5 | Config typed, YAML safe-load, validate, resolve defaults<file<env; unknown key reject mọi cấp | test CP3 |
| 6 | `core/domain`+`core/ports`+`application/ports` không import sqlite3/yaml/typer/langgraph/litellm/provider; `workspace` không import sqlite3/persistence | **AST** test CP7/CP5 |
| 7 | CLI chỉ delivery adapter (3 lệnh), exit code 0/1/2/3/4 ổn định | test CP7 |
| 8 | DB bootstrap đúng theo trạng thái (empty/partial/version>); CHECK enforced; integrity-verified (không tin `IF NOT EXISTS`) | test CP4 |
| 9 | Không dependency/feature phase sau (chỉ thêm PyYAML) | diff `pyproject.toml` |
| 10 | Không file source >350 dòng | file-size gate |
| 11 | Giá trị layout/path/version tập trung `workspace/layout.py`/`config/constants.py`; không literal lặp — audit review checklist CP8 | review CP8 |
| 12 | Test bao phủ happy + failure (config lỗi, nest hỏng/clone/nested/format, DB corrupted/schema mismatch, init-không-corrupt) | test CP3–CP7 |
| 13 | `python -m scripts.quality.gate` → 5/5 PASS | gate output |
| 14 | Path qua `pathlib`; test chạy dev OS (Windows). **Không tuyên bố** đa nền tảng đã chứng minh | ghi chú CP8 |
| 15 | `docs/plans/PHASE_1_COMPLETION_REPORT.md` tồn tại với evidence | CP8 |

> Wording đã loại: "code sạch", "resume-ready" (→ "canonical-serialized stable; resume ở P4"), "cross-platform". "CRUD" diễn giải rõ §7.3.

---

## 22. Phase 1 closure audit checklist

- [ ] `python -m scripts.quality.gate` 5/5 PASS (capture output).
- [ ] DoD §21 mục 1–15 mỗi mục có evidence.
- [ ] Snapshot layout `.ant/` + `.ant/.gitignore`.
- [ ] AST import-boundary report (core/domain + core/ports + application/ports; workspace ∌ sqlite3).
- [ ] NestState aggregate matrix (§12.2) test PASS, đúng exit 3/4 theo origin.
- [ ] Test clone-lifecycle (CONFIGURED→PROVISIONED) + SQLite bootstrap partial/corrupted PASS.
- [ ] `pyproject.toml` chỉ thêm PyYAML; không file >350 dòng.
- [ ] (Nhiệm vụ implementation riêng) cập nhật ROADMAP Phase 1 → COMPLETED + §14 — sau audit PASS.

---

## 23. Traceability: requirement → decision → checkpoint → test → DoD

| Domain/requirement | Source | Decision | Checkpoint | Test | DoD |
|---|---|---|---|---|---|
| Task lifecycle persistence | ROADMAP DoD | D05,D08,D09,D21 | CP2,CP6 | round-trip Task | §21.2 |
| WorkerRun lifecycle | ROADMAP DoD | D05,D21 | CP2,CP6 | round-trip WorkerRun | §21.2 |
| EnergyUsage append/read + ownership | ROADMAP DoD | D05,D19,D21 | CP2,CP6 | CHECK + ownership + list_by_* | §21.2 |
| WorkflowCheckpoint | ROADMAP DoD | D33 | CP2,CP6 | canonical-stable | §21.3 |
| Approval resolve-once (immutable) | ROADMAP DoD/§9 | D07,D31 | CP2,CP6 | resolve + double-resolve reject | §21.3 |
| ExecutionEvidence | ROADMAP §8 | D05,D21 | CP2,CP6 | round-trip | §21.4 |
| HandoffRecord | ROADMAP §8 | D05,D21 | CP2,CP6 | round-trip | §21.4 |
| PheromoneRecord | ROADMAP §8 | D05,D19,D26 | CP2,CP6 | round-trip (expires_at, confidence) | §21.4 |
| MemoryRecord | ROADMAP §7 | D19,D26 | CP2,CP6 | round-trip + deprecate | §21.4 |
| Task terminal incl REJECTED | ROADMAP §9 | D06,D32 | CP1 | enum/membership | §21.2 |
| State model | WORKFLOW_SPEC §15 + ROADMAP §9 | D06,D28 | CP1 | enum/membership | §21.2 |
| Provider-neutral domain | ADR-0001..0005 | D01,D23,D29 | CP1,CP2,CP5,CP7 | AST import-boundary | §21.6 |
| Typed config + precedence + missing-config | ROADMAP §8 | D10,D11,D12 | CP3 | config happy/negative | §21.5 |
| Workspace lifecycle + git-clone | ROADMAP §8 + PROJECT_STRUCTURE §4 | D13–D17,D30 | CP5,CP7 | state matrix, clone→provision, atomic | §21.1 |
| NestState aggregate ownership | (kiến trúc) | D29,D30 | CP4,CP5,CP7 | aggregate matrix, AST | §21.1,6 |
| SQLite bootstrap/version | TECHNICAL_FOUNDATION §3.7 + ADR-0005 | D19,D20,D22 | CP4 | empty/partial/version> | §21.8 |
| Checkpoint payload contract | (kiến trúc) | D33 | CP6 | canonical-stable | §21.3 |
| Repository decoupled | ADR-0005 | D04,D21 | CP2,CP6 | contract test trên SQLite | §21.2–4 |
| CLI mỏng | ROADMAP/PROJECT_STRUCTURE | D24,D25 | CP7 | CliRunner, exit codes | §21.7 |
| Nested Nest (APPROVED) | PO | D14 | CP5 | nested→error | §21.1 |
| Git policy (APPROVED) | PO | D18 | CP5 | `.gitignore` test | §21.1 |

---

## 24. Tóm tắt các patch cuối đã áp dụng

1. **Workspace state ABSENT** redefine: ABSENT = `.ant/` hoàn toàn không tồn tại; thiếu config/marker = FILES_CORRUPTED (§12.2).
2. **NestState ownership split** (D30): `WorkspaceArtifactState` (workspace) + `DatabaseState` (persistence) + `NestState` aggregate (application/models); workspace không import sqlite3; DB-origin→PersistenceError(4), workspace-origin→WorkspaceError(3); `NestFormatIncompatible` ≠ `SchemaVersionMismatch`.
3. **ApprovalDecision → ApprovalStatus** (D31): pending không phải decision; Approval immutable, `resolve()` trả bản mới; MemoryRecord.deprecate trả bản mới; column `approvals.status`.
4. **Bỏ Approval→Task coupling P1** (§7.2): chỉ persist `ApprovalStatus.rejected` + `TaskStatus.rejected`; transition orchestration thuộc Phase 4.
5. **EnergyUsage contract** (Patch5): ops `append/get/list_by_task/list_by_worker_run`; CHECK(task_id OR worker_run_id); validate ownership khi cả hai có.
6. **D33** checkpoint payload contract tách khỏi D28 (transition validation); Decision Register liên tục D01–D33.
7. **Bootstrap siết** (Patch7): phân biệt empty/partial/corrupted/version>; không tin `CREATE TABLE IF NOT EXISTS`; CP4 test partial + bootstrap x2.
8. **Enum sourcing** (GĐ-9): TaskPriority.low/high & ConfidenceLevel.low đánh dấu assumption; CHECK chỉ tạo khi có traceability.
9. **PO APPROVED**: D14 (cấm nested Nest), D18 (git safety policy).
10. Integrity: heading §1–§24 liên tục; D01–D33 liên tục; CP1–CP8 đầy đủ 13 trường.
