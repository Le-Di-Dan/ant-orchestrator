# PHASE 7 — Minimal Memory Retrieval, CLI/API Surface & MVP Hardening — Implementation Plan

> **Trạng thái plan**: `PLANNING_REVISION_2 — PENDING_REVIEW`
> **Loại task**: PLANNING ONLY — chưa implement. Canonical artifact.
> **Baseline xác nhận**: branch `develop`, HEAD `96ee8e4`, working tree clean.
> Phase 6 `COMPLETED` — 1786 passed / 15 skipped / 0 failed.
> **Revision 2**: giải quyết thêm 19 correction từ reviewer.

---

## Context

Phase 6 đã đóng (HEAD `96ee8e4`). Phase 7 là phase cuối của giai đoạn MVP: bổ sung memory
retrieval tối thiểu deterministic, hoàn thiện CLI surface, thêm FastAPI surface tối thiểu, và
hardening đủ để vượt MVP Release Gate.

**Trọng tâm Phase 7**:
1. `memory_records` thiếu `task_id` → migration v4 + mở rộng repository
2. Retrieval tối thiểu: filter type/task_id/source/confidence/tags, bounded limit, stable ordering
3. Memory records đưa vào `ContextPackage` qua `MemoryContextEntry` DTO + rendered text source
4. CLI hoàn chỉnh: `logs`, `memory search` (trên nền Phase 4 CLI đã có)
5. FastAPI tối thiểu: Model A (two-step), `create_app(workspace)` factory, phân biệt WorkflowRun/WorkerRun
6. Neutral composition root dùng chung CLI và API
7. Restart recovery evidence: 3 levels (app-instance / service reinit / real subprocess)
8. Release validation offline/deterministic

**Không thay đổi**: Foundation, Technical Foundation, ADR-0001–0007, ROADMAP, source code, tests,
dependencies.

---

## A. Repository Audit

### A.1 Preflight

| Hạng mục | Giá trị xác nhận |
|---|---|
| Branch | `develop` |
| HEAD | `96ee8e4` |
| Working tree | clean |
| Phase 6 dependency | COMPLETED (1786 passed / 15 skipped / 0 failed) |
| Schema version | v3 (`persistence/schema_common.py: CODE_MAX_VERSION = 3`) |
| Quality gate | `scripts/quality/gate.py`: gates = ruff-lint / ruff-format / mypy / file-size / pytest (một lần) |

### A.2 File/module traced

```
core/domain/entities.py         — Task, WorkerRun (WorkerRunId)
core/domain/workflow.py         — WorkflowRun (WorkflowRunId), ExecutionAttempt, ResumeOperation
core/domain/records.py          — MemoryRecord frozen dataclass (no task_id; no KV metadata)
                                  PheromoneRecord có task_id: TaskId|None — pattern tham chiếu
core/ports/repositories.py      — MemoryRepository Protocol (append/get/deprecate/list_by_type)
                                  WorkflowRunRepository, WorkerRunRepository, ExecutionAttemptRepository
persistence/repositories/memory.py — SqliteMemoryRepository; _to_memory() là DUY NHẤT constructor của MemoryRecord trong production
persistence/migration_v3.py     — pattern cho migration mới
persistence/migrations.py       — SqliteDatabaseBootstrapper chain v2→v3
persistence/schema_common.py    — CODE_MAX_VERSION=3, MIGRATIONS_TABLE
context/store.py                — ContextPackageStore: persist()/verify()/load(); load() trả tuple[LoadedSource,...]
                                  _write_sources() ghi sources/<idx>.txt; artifact_files dict trong manifest.json
                                  _verify_sources(): đọc từ canonical["sources"] list
context/digest.py               — canonical_context_manifest() → dict; manifest_digest() → str
context/package.py              — ContextPackage, ContextManifest, ContextBuildRequest (files only)
context/budget.py               — ContextBudget, BudgetTracker.can_fit()/consume()
application/services/run_workflow.py — execute(): terminal task → WorkflowStateError;
                                  active run → _handle_existing_run() (RESUME, không phải reject);
                                  else → _create_and_invoke()
application/ports/audit.py      — AuditEventType (8 types); AuditSink Protocol
adapters/jsonl_audit_sink.py    — JsonlAuditSink → .ant/logs/audit-<date>.jsonl; per-event JSON
scripts/quality/gate.py         — GATES: ruff-lint/ruff-format/mypy/file-size/pytest (một subprocess each); KHÔNG có riêng docker gate
```

### A.3 MemoryRecord writers (audit thực tế)

**Trong production code**: `MemoryRecord(...)` chỉ được tạo bởi `SqliteMemoryRepository._to_memory()` (deserialization). **Không có application service nào gọi `memory_repository.append()`.**

**Hàm ý**: Phase 7 integration tests phải seed records thủ công. Worker context retrieval sẽ tìm được records sau khi writer service (post-MVP) được implement. Plan ghi rõ limitation này.

### A.4 Gaps phát hiện

| Gap | Hàm ý |
|---|---|
| MemoryRecord thiếu task_id; không có KV metadata | Migration v4; "metadata filter" = filter trên structured fields |
| Không có production MemoryRecord writer | Test phải seed; real writer là post-MVP |
| MemoryRepository không có search() | Cần thêm; criteria tại core/domain/ |
| ContextPackage/ContextManifest không có memory section | Cần optional fields; MemoryContextEntry DTO |
| context/store.py._write_sources() chỉ ghi file artifacts | Cần ghi rendered memory text như 1 source |
| canonical_context_manifest() chỉ cover file artifacts | Cần include memory entries |
| WorkflowRun và WorkerRun là hai entity khác nhau | API phải dùng riêng: /workflow-runs và /worker-runs |
| RunWorkflow.execute() RESUME active run (không reject) | API phải reflect resume semantics, không 409 |
| FastAPI chưa có; api/ trống | Cần thêm dep + factory |
| build_workflow_services() ở cli/ → API không thể import | Cần neutral composition root |
| Không có AuditLogReader port | Cần port + adapter |
| AuditEventType thiếu MEMORY_RETRIEVAL | Cần thêm |

---

## B. Architecture Map

```
core/domain         ← core/ports           ← application/ports
                                           ← application/services (ports only, not concrete adapters)
                    ← persistence/ (adapters + repositories)
                    ← context/ (package, digest, store, budget, preparation)
                    ← workflows/ (LangGraph confined to graph.py/runner.py/checkpointer.py)
                    ← composition.py (NEW — neutral, top-level, wires everything)
                    ← cli/ (delivery — imports composition.py)
                    ← api/ (delivery — imports composition.py, NOT cli/)
```

**Three entity types (phân biệt rõ)**:
- `WorkflowRun` (`WorkflowRunId`) — LangGraph execution cursor; status: RUNNING/AWAITING_APPROVAL/COMPLETED/FAILED/CANCELLED
- `WorkerRun` (`WorkerRunId`) — legacy worker execution entity (1 per task execution); status: PENDING/RUNNING/COMPLETED/FAILED
- `ExecutionAttempt` (`ExecutionAttemptId`) — 1 attempt of 1 logical action (có thể nhiều per WorkerRun)

---

## C. Locked Design Decisions

### C.1 task_id trên MemoryRecord

**Quyết định**: Thêm `task_id: TaskId | None = None` vào `MemoryRecord` (song song với
`PheromoneRecord.task_id`). Migration v4: nullable FK column. Existing rows → NULL.

### C.2 Colony/project filter

"Colony/project scope" = workspace đang mở (`.ant/`). Mỗi DB file đã scoped. Không cần
`colony_id`. Test isolation: hai `tmp_path` workspaces riêng biệt với DB riêng.

### C.3 MemorySearchCriteria contract

#### Metadata trong MemoryRecord

Structured fields sẵn có = metadata: `type (MemoryType)`, `confidence (ConfidenceLevel)`,
`source (str)`, `tags (tuple[str,...])`. Không có KV metadata field nào khác. "Metadata filter"
của Phase 7 = filter trên các structured fields này.

#### MemorySearchCriteria (tại `core/domain/query.py` — NEW)

```python
@dataclass(frozen=True, slots=True)
class MemorySearchCriteria:
    memory_type: MemoryType | None = None       # exact equality; None = not filtered
    task_id: TaskId | None = None               # exact FK equality; None = not filtered
    source: str | None = None                  # case-sensitive exact equality; None = not filtered
    confidence: ConfidenceLevel | None = None  # exact enum equality; None = not filtered
    tags: tuple[str, ...] = ()                 # ANY semantics; () = not filtered
    include_deprecated: bool = False
    limit: int = 1                             # must be positive; default resolved by service
```

**Layer**: `core/domain/query.py` — bắt buộc vì `core/ports/repositories.py` phải tham chiếu type
này, và import boundary test chỉ cho phép `core/ports` import từ `core/domain`. Không import
`config/constants.py` (forbidden cho core/domain). `limit` phải là positive integer (không sentinel).

**Không có `MemoryOrdering` enum** — MVP luôn dùng `created_at DESC, id ASC`. Không có caller
nào cần ordering lựa chọn.

#### MemorySearchRequest (tại service layer)

```python
@dataclass(frozen=True)
class MemorySearchRequest:           # application input DTO
    memory_type: str | None = None
    task_id: str | None = None
    source: str | None = None
    confidence: str | None = None
    tags: tuple[str, ...] = ()
    include_deprecated: bool = False
    limit: int | None = None         # None → default; 0/negative → validation error
```

**Service validation**:
- `limit is None` → resolve `MEMORY_DEFAULT_LIMIT`
- `limit <= 0` → raise `DomainError("limit must be positive")`
- `limit > MEMORY_MAX_LIMIT` → raise `DomainError(...)`
- Empty tag string → raise `DomainError("tag cannot be empty string")`
- Invalid enum string → raise `DomainError`

**CLI/API**: `--limit N` option absent → `None`; explicit `--limit 0` → CLI validates and exits
`EXIT_USAGE`. API omit → None; `limit=0` → 422.

#### SQL query pattern (trong `SqliteMemoryRepository.search()`)

```sql
SELECT {_COLUMNS} FROM memory_records
WHERE (deprecated = 0 OR deprecated IS NULL)  -- include_deprecated=False
  [AND type = ?]             -- if memory_type not None
  [AND task_id = ?]          -- if task_id not None
  [AND source = ?]           -- if source not None (case-sensitive)
  [AND confidence = ?]       -- if confidence not None
  [AND EXISTS (
      SELECT 1 FROM json_each(tags_json)
      WHERE value IN ({placeholders})
  )]                         -- if tags not empty (ANY semantics)
ORDER BY created_at DESC, id ASC
LIMIT ?                      -- resolved positive integer
```

`include_deprecated=True` → không thêm deprecated predicate (không phải `deprecated = NULL`).
No Python-side tag filter. No `MEMORY_INNER_FETCH_LIMIT`.

#### SQLite JSON1 capability

`json_each()` thuộc JSON1, bật mặc định từ SQLite 3.38.0 (2022). Không hard-code version string.
`SqliteDatabaseBootstrapper.bootstrap()` chạy injectable capability checker:

```python
def _verify_json1(conn: sqlite3.Connection) -> None:
    try:
        conn.execute("SELECT count(*) FROM json_each('[]')").fetchone()
    except sqlite3.OperationalError as exc:
        raise StorageIntegrityError("SQLite JSON1 extension required") from exc
```

Injectable → testable: test failure path qua mock/stub connection mà raises `OperationalError`.
Fail-fast, không fallback.

#### MemoryRecord writers — production vs test

**Production**: không có writer service trong Phase 7. `memory_repository.append()` chỉ được gọi
trong tests. **Phase 7 runtime selection** tìm records trong workspace DB — chỉ tìm thấy nếu
records đã được seeded trước (test) hoặc bởi future writer service (post-MVP).

**Integration test phải seed records** trước khi chạy workflow. Plan không giả định workflow tự
tạo records.

**Post-MVP**: cần writer service gọi `append()` sau workflow completion. Đây là phase sau MVP scope.

**Selection policy (MVP default)**:
```
criteria = MemorySearchCriteria(
    task_id=TaskId(current_task_id),  # always filter by current task
    # all other filters = None/() → no restriction
    include_deprecated=False,
    limit=<resolved MEMORY_DEFAULT_LIMIT>,
)
```
Behavior khi không có records → trả `()` → `memory_entries = ()` → `memory_section = None`.

### C.4 MemoryContextEntry DTO (single representation)

Canonical representation duy nhất cho context-facing memory:

```python
@dataclass(frozen=True, slots=True)
class MemoryContextEntry:
    """Immutable context-facing DTO. MemoryRecord → MemoryContextEntry tại selection time."""
    record_id: str                  # identity for manifest/digest
    type_value: str                 # MemoryType.value
    task_id_value: str | None       # TaskId.value or None
    source: str
    confidence_value: str           # ConfidenceLevel.value
    title: str
    summary: str
    tags: tuple[str, ...]           # sorted alphabetically (stable)

    def rendered_text(self) -> str:
        """Exact text fed to worker; budget + store + digest all based on this."""
        tag_line = ", ".join(self.tags) if self.tags else "none"
        return (
            f"[{self.type_value}] {self.title}\n"
            f"Source: {self.source} | Confidence: {self.confidence_value} | Tags: {tag_line}\n"
            f"{self.summary}"
        )

    def to_canonical(self) -> dict[str, object]:
        """Stable JSON for digest (sorted keys implicitly — caller sorts)."""
        return {
            "confidence": self.confidence_value,
            "id": self.record_id,
            "source": self.source,
            "summary": self.summary,
            "tags": list(self.tags),  # already sorted
            "task_id": self.task_id_value,
            "title": self.title,
            "type": self.type_value,
        }
```

**Single representation rules**:
- `MemoryRecord` → `MemoryContextEntry` tại `ContextPackageBuilder.build()` (không trước, không sau)
- Budget = `TokenEstimator.estimate(entry.rendered_text())`
- Digest = `canonical_context_manifest()` includes entries in their **selection order** (không sort by ID)
- Store = rendered text của TẤT CẢ entries được join thành một source file `memory://ant/context`
- Worker nhận `LoadedSource(path="memory://ant/context", content=combined_rendered_text)` qua `store.load()`
- Tags sorted trong `MemoryContextEntry.tags` (stable input → stable digest)

### C.5 Canonical digest (record-order preserving)

**`canonical_context_manifest()` update**:

```python
def canonical_context_manifest(package: ContextPackage) -> dict[str, object]:
    return {
        "manifest_schema_version": CONTEXT_MANIFEST_SCHEMA_VERSION,
        "sources": [
            {"path": normalize_source_path(a.path), "content_digest": source_digest(a.content), "estimated_tokens": a.estimated_tokens}
            for a in package.artifacts
        ],
        "memory_entries": [
            entry.to_canonical()
            for entry in package.memory_entries   # selection order preserved
        ],
    }
```

**Record order**: entries trong `canonical["memory_entries"]` là selection/budget order — không sort
by ID. **Digest changes nếu record order changes** (intentional: different ordering = different
context for worker).

**Tag stability**: `MemoryContextEntry.tags` đã sorted → `to_canonical()["tags"]` stable bất kể
input order.

**Tests bắt buộc**:
- Cùng entries cùng order → cùng digest
- Entries khác order → digest khác
- Thêm 1 entry → digest khác
- Tags khác input order nhưng cùng nội dung → digest không đổi (sort normalize)
- Persist + reopen: digest stable

### C.6 Context-memory store/load contract

**`_write_sources()` update** (tại `ContextPackageStore`):
- Nếu `package.memory_entries` không rỗng:
  - Join `entry.rendered_text()` cho mỗi entry với separator `\n---\n`
  - Ghi vào `staging/sources/memory_context.txt`
  - Add entry `artifact_files["memory://ant/context"] = "sources/memory_context.txt"` vào `artifact_files` dict
  - Add vào `canonical["sources"]`: `{"path": "memory://ant/context", "content_digest": source_digest(combined), "estimated_tokens": N}`
- `canonical["memory_entries"]` = `[entry.to_canonical() for entry in package.memory_entries]`

**`_verify_sources()` behavior**: không thay đổi — nó đọc `canonical["sources"]` và verify từng entry.
Memory text source được verify tự động như bất kỳ source nào khác.

**`load()` behavior**: trả `tuple[LoadedSource, ...]` bao gồm memory source. Worker nhận memory content
qua `LoadedSource(path="memory://ant/context", ...)`.

**Reopen existing old package** (không có `memory_entries` trong canonical): `canonical["memory_entries"]`
absent → treated as `[]` → `memory_section = None`. Không raise.

**Malformed memory JSON**: không applicable (memory không được parse từ JSON khi load; chỉ raw text).

**Digest mismatch**: `ManifestDigestMismatch` → fail closed (existing behavior, unchanged).

### C.7 Context-memory budget

- Budget = `TokenEstimator.estimate(entry.rendered_text())`
- Selection loop (trong `ContextSourcePreparerImpl`):
  1. `records = SearchMemory.execute(request)` → `Sequence[MemoryRecord]`
  2. Với mỗi record theo order (newest-first):
     - Convert → `MemoryContextEntry` (sort tags)
     - `tokens = TokenEstimator.estimate(entry.rendered_text())`
     - `if not budget_tracker.can_fit(tokens)`: skip, continue (không dừng)
     - `budget_tracker.consume(tokens)`, thêm entry vào `included`
  3. `package_request.memory_entries = tuple(included)`
- `budget_consumed_tokens` = sum của tokens thực tế included

### C.8 MemoryContextSection (structured manifest)

```python
@dataclass(frozen=True, slots=True)
class MemoryContextSection:
    """Structured filter evidence trong manifest — không có free-form summary string."""
    applied_task_id: str | None
    applied_memory_type: str | None
    applied_source: str | None
    applied_confidence: str | None
    applied_tags: tuple[str, ...]   # sorted, stable
    applied_include_deprecated: bool
    resolved_limit: int
    returned_count: int
    budget_consumed_tokens: int
    record_ids: tuple[str, ...]     # in selection order (parallel với entries)
    record_types: tuple[str, ...]   # in selection order (parallel với record_ids)
```

Không có `filter_summary: str`. Mọi field đều typed, immutable, explicit. Không thể làm lệch
parallel tuples `record_ids` / `record_types` vì cả hai được build từ cùng một `included` list.

### C.9 AuditLogReader port và algorithm

**Port** (`application/ports/audit_log_reader.py` — NEW):

```python
@dataclass(frozen=True, slots=True)
class AuditLogQuery:
    task_id: str | None
    limit: int          # positive resolved integer; caller provides default
    since: datetime | None  # UTC inclusive; None = no filter

@dataclass(frozen=True, slots=True)
class AuditLogPage:
    events: tuple[AuditEvent, ...]
    corrupt_count: int      # malformed JSON lines skipped
    files_scanned: int      # number of daily files read
    has_more: bool          # True nếu có events cũ hơn chưa trả do limit

class AuditLogReader(Protocol):
    def read(self, query: AuditLogQuery) -> AuditLogPage: ...
```

**Adapter algorithm** (`adapters/jsonl_audit_log_reader.py` — NEW):

```
1. List .ant/logs/audit-*.jsonl, sort descending by filename (newest day first)
2. buffer = []
3. For each file (newest first):
   a. If `since` is set and file's date (from filename) < since.date(): STOP (all older files also before since)
   b. Read ALL lines (append-order = oldest first within file)
   c. Parse each line as JSON; on JSONDecodeError: increment corrupt_count, skip
   d. Filter: task_id match (if set); since match (if set)
   e. Reverse filtered events (newest within this file first)
   f. Extend buffer with these reversed events
   g. If len(buffer) >= limit: set has_more=True, STOP
4. Return AuditLogPage(events=tuple(buffer[:limit]), ...)
```

**Newest-first guarantee**: within each file, reversing gives newest event first. Files traversed
newest-first. Overall result: newest matching event first.

**Memory bounded**: one daily file loaded at a time. Not entire history in RAM.

**Stable ordering**: `(created_at DESC, correlation_id ASC)` — same timestamp → `correlation_id`
lexicographic stable.

**`has_more` semantics**: `True` when the traversal stopped early due to limit (more events exist
in older files or later in current file). `False` when all matching events were scanned.

**Unreadable file**: raise `StorageIntegrityError`. Corrupt line: skip + `corrupt_count++`.

**`AuditLogQuery.limit`**: positive resolved integer — caller (service) provides via constants.
Port does NOT import config constants.

**Test requirement** (nouveauté): Seed 10 events in one file → `limit=5` → verify result = 5
NEWEST events (last 5 appended lines), NOT the 5 oldest (first 5 lines).

**`GetTaskLogs` returns `AuditLogPage`**, not just `tuple[AuditEvent, ...]`. CLI/API read
`page.events`, `page.corrupt_count`, `page.files_scanned`, `page.has_more`.

### C.10 API resource model (WorkflowRun vs WorkerRun)

**Entity phân biệt**:
- `WorkflowRun` — graph execution cursor; ID type = `WorkflowRunId`
- `WorkerRun` — worker execution entity; ID type = `WorkerRunId`
- Không được dùng `/runs/{id}` mơ hồ

**API endpoints (Model A — two-step)**:
```
POST /tasks                          → 201 {task_id, title, status: "pending", ...}
POST /tasks/{task_id}/workflow-runs  → 200 {workflow_run_id, status, approval_id?}
GET  /tasks/{task_id}                → 200 TaskDetailResponse (includes workflow_run summary, worker_runs, energy, approvals)
GET  /workflow-runs/{workflow_run_id} → 200 WorkflowRunDetailResponse (optional, nếu cần cho API follow-up)
GET  /worker-runs/{worker_run_id}    → 200 WorkerRunDetailResponse (đáp ứng ROADMAP "inspect worker run")
GET  /logs?task_id=&limit=&since=   → 200 LogsResponse (with has_more, corrupt_count)
```

**`POST /tasks/{task_id}/workflow-runs` semantics** (reflect actual `RunWorkflow.execute()`):
- Task terminal → `WorkflowStateError` → **422**
- Active run exists → **RESUME** (không phải 409) → return existing run status (may be `WAITING_FOR_APPROVAL` or final)
- No active run → create + invoke → return result

Route không tự query DB để check active run. Gọi cùng `RunWorkflow` service với CLI. Service
handles all cases.

**Response fields**:
- `POST /tasks/{task_id}/workflow-runs` returns `{workflow_run_id, status, approval_id}` (approval_id là None nếu không interrupt)
- `GET /tasks/{task_id}` TaskDetailResponse: `task_id, title, status, active_workflow_run: WorkflowRunSummary | None, worker_runs: [...], energy: EnergyTotalsView, approvals: [...]`

**Energy và approval visibility** (thêm explicit):
- `TaskDetailView.energy_totals` = aggregate từ `EnergyUsageRepository.list_by_task(task_id)`
- `TaskDetailView.approvals` = từ `ApprovalRepository.list_by_task(task_id)` (cả pending + resolved)
- `WorkerRunDetailView.energy` = từ `EnergyUsageRepository.list_by_worker_run(worker_run_id)`
- Bounded: không có unbounded join; mỗi list capped tại reasonable limit (100)

**Error mapping**:
- `RecordNotFound` → 404
- `WorkflowStateError` → 422
- `DomainError` → 422
- Persistence errors → 503
- Unhandled → 500 (sanitized message, no traceback, no secret)

### C.11 FastAPI factory và neutral composition root

**`create_app(workspace: Path) → FastAPI`** — factory; không có global `app = FastAPI()`.

**`create_default_app() → FastAPI`** — zero-arg factory cho uvicorn:
```
uvicorn ant_orchestrator.api.main:create_default_app --factory --host 127.0.0.1 --port 8080
```

**Neutral composition root** (`src/ant_orchestrator/composition.py` — NEW):
- Chứa `WorkflowServices` dataclass + `build_workflow_services(workspace: Path) → WorkflowServices`
- Import từ `persistence`, `application`, `adapters` — không từ `cli/` hay `api/`
- `cli/workflow_composition.py` → thin re-export wrapper (backward compat)
- `api/dependencies.py` → import từ `ant_orchestrator.composition`

`WorkflowServices` Phase 7:
```python
@dataclass(frozen=True)
class WorkflowServices:
    create_task: CreateTask
    run_workflow: RunWorkflow
    resolve_approval: ResolveApproval
    cancel_task: CancelTask
    reconciler: WorkflowReconciler
    task_status: GetTaskStatus
    search_memory: SearchMemory          # NEW
    get_task_detail: GetTaskDetail       # NEW
    get_worker_run_detail: GetWorkerRunDetail  # NEW
    get_task_logs: GetTaskLogs           # NEW
```

### C.12 Schema migration v4

`ALTER TABLE memory_records ADD COLUMN task_id TEXT REFERENCES tasks(id)` (nullable, backward-compat).
Index `idx_mem_task ON memory_records(task_id)`. `CODE_MAX_VERSION = 4`.

### C.13 Restart recovery (3 levels)

**Level 1 — App-instance restart** (in-process context manager):
```python
with TestClient(create_app(workspace)) as client_a:
    resp = client_a.post("/tasks", ...)
    task_id = resp.json()["task_id"]
    client_a.post(f"/tasks/{task_id}/workflow-runs")  # reaches approval interrupt
# client_a lifespan đóng hoàn toàn

with TestClient(create_app(workspace)) as client_b:  # same workspace, new app instance
    detail = client_b.get(f"/tasks/{task_id}")
    assert detail.json()["status"] == "waiting_for_approval"
```

**Level 2 — Service reinitialization** (in-process, không phải process restart):
```python
svc_a = build_workflow_services(tmp_path)
task_id, approval_id = seed_approval_pause(svc_a, tmp_path)
# Explicitly drop svc_a (no lifecycle close needed — SQLite connections closed per UoW)
svc_b = build_workflow_services(tmp_path)
status = svc_b.task_status.get(task_id)
assert status.status == TaskStatus.WAITING_FOR_APPROVAL
```

**Level 3 — Real subprocess restart** (actual process boundary):
```python
# Process A subprocess
result_a = subprocess.run(
    [sys.executable, "-m", "ant_orchestrator.cli", "init", "--path", str(tmp_path)],
    capture_output=True, check=True
)
result_b = subprocess.run(
    [sys.executable, "-m", "ant_orchestrator.cli", "task", "create", "--title", "T", "--path", str(tmp_path)],
    capture_output=True, check=True
)
task_id = json.loads(result_b.stdout)["task_id"]
# subprocess.run với ant run → hits approval interrupt; writes IDs to stdout JSON
result_c = subprocess.run(
    [sys.executable, "-m", "ant_orchestrator.cli", "run", task_id, "--json", "--path", str(tmp_path)],
    capture_output=True, check=True  # process exits after interrupt is persisted
)
run_out = json.loads(result_c.stdout)
approval_id = run_out["approval_id"]

# Process B: new subprocess
result_d = subprocess.run(
    [sys.executable, "-m", "ant_orchestrator.cli", "status", "--json", "--path", str(tmp_path)],
    capture_output=True, check=True
)
status_out = json.loads(result_d.stdout)
assert any(t["task_id"] == task_id and t["status"] == "waiting_for_approval"
           for t in status_out["tasks"])
```

Level 3 dùng `subprocess.run()` với CLI commands — là actual new Python interpreter process,
không phải `del svc_a`. Approval interrupt được seeded qua energy gate (threshold LOW).

---

## D. Scope-Control Table

| Capability | Phase 7 | Deferred | Lý do |
|---|---|---|---|
| Filter memory: type, task_id, source, confidence | ✓ | | Core DoD; metadata = structured fields |
| Filter memory: tags ANY (SQL json_each) | ✓ | | Core DoD; SQL-level |
| Bounded limit + stable ordering (newest-first) | ✓ | | Core DoD |
| MemoryContextEntry DTO + rendered text source | ✓ | | Canonical representation |
| Context manifest with structured filter evidence | ✓ | | Core DoD |
| Memory token budget | ✓ | | Correctness |
| Canonical digest (record-order preserving) | ✓ | | Anti-TOCTOU |
| CLI: ant logs + ant memory search | ✓ | | Phase 7 DoD |
| FastAPI: POST /tasks, POST /tasks/{id}/workflow-runs | ✓ | | Phase 7 DoD |
| FastAPI: GET /tasks/{id}, GET /worker-runs/{id} | ✓ | | Phase 7 DoD |
| FastAPI: GET /workflow-runs/{id} | ✓ | | Phase 7 DoD (follow-up inspect) |
| FastAPI: GET /logs | ✓ | | Phase 7 DoD |
| Neutral composition root | ✓ | | Architecture |
| AuditLogReader port + newest-first JSONL adapter | ✓ | | Architecture |
| Restart recovery: 3 levels | ✓ | | MVP Release Gate |
| SQLite JSON1 capability check (injectable) | ✓ | | Correctness |
| ADR-0008 (deliverable of CP0) | ✓ | | Architecture record |
| Migration chain v1→v4 tests | ✓ | | Correctness |
| Production MemoryRecord writer service | | ✓ | Post-MVP |
| Configurable MemoryOrdering | | ✓ | No MVP caller |
| Semantic/vector retrieval | | ✓ | Out-of-MVP |
| FastAPI memory search endpoint | | ✓ | Not in ROADMAP Phase 7 |
| Authentication/authorization | | ✓ | Local MVP only |
| WebSocket/SSE/streaming, distributed tracing | | ✓ | Out-of-MVP |
| Web UI, multi-tenant server | | ✓ | Out-of-MVP |

---

## E. Checkpoint Decomposition

### CP0 — Contract & Constants Bootstrap

**Mục tiêu**: Lock all design decisions; create constants; prepare ADR-0008.

**Files tác động**:
- `config/constants.py` — ADD: `MEMORY_DEFAULT_LIMIT = 20`, `MEMORY_MAX_LIMIT = 100`,
  `LOG_DEFAULT_LIMIT = 50`, `LOG_MAX_LIMIT = 200`, `API_BIND_HOST = "127.0.0.1"`, `API_BIND_PORT = 8080`
- `application/ports/audit.py` — ADD `AuditEventType.MEMORY_RETRIEVAL`
- `docs/decisions/ADR-0008-phase7-memory-retrieval.md` — NEW (per ADR-0001–0007 format)

**Không có `MEMORY_INNER_FETCH_LIMIT`**.

**Steps**: add constants → add enum value → write ADR-0008 → verify file sizes ≤ 350 lines.

**Tests**: constants in range (`DEFAULT < MAX`); `AuditEventType.MEMORY_RETRIEVAL.value` valid.

**Gate**: targeted. **Dependency**: Phase 6 COMPLETED.
**Commit**: `feat(phase7-cp0): lock Phase 7 constants, audit event type, ADR-0008`

---

### CP1 — Schema Migration v4

**Mục tiêu**: task_id trên memory_records; full chain tests.

**Files**:
```
core/domain/records.py              — ADD task_id: TaskId | None = None
persistence/schema.py               — EXPECTED_SCHEMA update; DDL update; idx_mem_task
persistence/schema_common.py        — CODE_MAX_VERSION 3 → 4
persistence/migration_v4.py         — NEW: SqliteDatabaseMigratorV4
persistence/migrations.py           — register v4; add JSON1 capability check in bootstrap
persistence/repositories/memory.py  — update _COLUMNS, _to_memory(), append()
```

**Migration semantics**: v3→v4 idempotent; fail-closed if version ≠ 3; transaction; index added.

**Test cases** (`tests/test_migration_v4.py` — NEW):
- Fresh install → v4
- v3 → v4: column + index + migrations row
- v2 → v3 → v4 chain: OK
- v1 → v2 → v3 → v4 chain: OK
- Idempotent: v4 → v4 no-op
- v2 → v4 (skip v3): `SchemaVersionMismatch`
- Round-trip `MemoryRecord` with task_id / without task_id
- JSON1 capability check failure: injectable mock raises `OperationalError` →
  `bootstrap()` raises `StorageIntegrityError`
- Cross-workspace: two tmp_path DBs; no record leak

**Gate**: targeted. **Dependency**: CP0.
**Commit**: `feat(phase7-cp1): schema v4 — task_id on memory_records, migration chain, JSON1 check`

---

### CP2 — Memory Domain Types & SQL Retrieval

**Mục tiêu**: `MemorySearchCriteria` tại đúng layer; `search()` với `json_each()`; full filter tests.

**Files**:
```
core/domain/query.py                   — NEW: MemorySearchCriteria
core/ports/repositories.py             — ADD search(criteria) → Sequence[MemoryRecord]
persistence/repositories/memory.py     — implement search()
```

**`search()` builds WHERE dynamically** — list comprehension; no string concat with raw input.
`include_deprecated=True` → no deprecated predicate (not `deprecated = NULL`).
`include_deprecated=False` → `deprecated = 0 OR deprecated IS NULL` (SQLite stores 0 for False, NULL for NULL).

**Tests** (`tests/test_phase7_memory_retrieval.py`):
- All filter fields (type, task_id, source, confidence, tags, include_deprecated)
- `source="user"` → case-sensitive exact; `source="User"` → no match
- `tags=("x","y")` → ANY semantics; records with "x" OR "y" returned
- No-dump: 50 records → `search(criteria_limit=5)` → 5 returned
- Ordering: newest-first, stable
- Empty → `()`; no raise
- `limit=0` → prevented at service layer; criteria requires positive int
- Cross-workspace: 2 workspaces → no leak
- Combined filter intersection

**Gate**: targeted. **Dependency**: CP1.
**Commit**: `feat(phase7-cp2): memory search criteria + SQL json_each retrieval`

---

### CP3 — Application Services & Ports

**Mục tiêu**: `SearchMemory` + `AuditLogReader` port + query services; all depend on ports not concrete adapters.

**Files**:
```
application/ports/audit_log_reader.py         — NEW: AuditLogQuery, AuditLogPage, AuditLogReader Protocol
application/services/search_memory.py         — NEW: MemorySearchRequest, MemorySearchResult, SearchMemory
application/services/get_task_detail.py       — NEW: TaskDetailView, GetTaskDetail
application/services/get_worker_run_detail.py — NEW: WorkerRunDetailView, GetWorkerRunDetail
application/services/get_task_logs.py         — NEW: GetTaskLogs (nhận AuditLogReader port; returns AuditLogPage)
adapters/jsonl_audit_log_reader.py            — NEW: JsonlAuditLogReader (algorithm xem C.9)
application/models/views.py                   — ADD view types (EnergyTotalsView, ApprovalView, etc.)
```

**`GetTaskLogs.query()` → returns `AuditLogPage`** (không strip metadata):
- `page.events` — tuple of LogEntry
- `page.corrupt_count` — malformed lines
- `page.files_scanned` — files read
- `page.has_more` — whether older events exist

**`GetTaskDetail`** includes energy + approvals:
- `energy_totals = EnergyUsageRepository.list_by_task(task_id)` (aggregated)
- `approvals = ApprovalRepository.list_by_task(task_id)` (cả pending + resolved)

**Tests** (`tests/test_phase7_query_services.py`):
- SearchMemory: valid request; limit=None → DEFAULT; limit=0 → error; limit>MAX → error; empty tag → error
- SearchMemory writes AuditEvent(MEMORY_RETRIEVAL); detail no content/title/summary
- GetTaskDetail: task with runs + energy + approvals → full view
- GetTaskLogs returns AuditLogPage; strip NOT done
- Newest-first test: 10 events in one file, limit=5 → 5 NEWEST returned (not 5 oldest)
- `has_more=True` when stopped early; `has_more=False` when all scanned
- `corrupt_count > 0` when corrupt lines present; `files_scanned` matches traversal
- Import boundary: services do NOT import `persistence/` directly

**Gate**: targeted. **Dependency**: CP2.
**Commit**: `feat(phase7-cp3): search-memory service, audit-log-reader port, query services`

---

### CP4 — Context Package Building Blocks

**Mục tiêu**: `MemoryContextEntry` DTO; update `ContextPackage`/`ContextManifest`/`ContextBuildRequest`; update `canonical_context_manifest()` + `_write_sources()`; `MemoryContextSection` structured manifest.

**CP4 owns building blocks only. `ContextSourcePreparerImpl` wiring is in CP5.**

**Files**:
```
context/package.py          — ADD MemoryContextEntry, MemoryContextSection, ContextPackage.memory_entries, ContextManifest.memory_section; ContextBuildRequest.memory_entries
context/digest.py           — UPDATE canonical_context_manifest(): include memory_entries in selection order
context/store.py            — UPDATE _write_sources(): write memory_context.txt as source; UPDATE _verify_sources(): handles memory source (standard path)
application/ports/context_builder.py  — ADD memory_entries: tuple[MemoryContextEntry, ...] = ()
```

**Backward compat**: all new fields are optional with empty/None defaults. Existing tests unaffected.

**Digest**: `canonical["memory_entries"] = [e.to_canonical() for e in package.memory_entries]`
in **selection order** (not sorted by ID). If entries order changes → digest changes.

**Store**: combined rendered text stored as `sources/memory_context.txt`; path key
`"memory://ant/context"` in `artifact_files`. The combined text is also added to `canonical["sources"]`
with its content_digest. `_verify_sources()` verifies it automatically.

**Reopen old package** (no `memory_entries` in canonical): treated as `[]` → `memory_section = None`.

**Tests** (`tests/test_phase7_context_memory.py`):
- Build with `memory_entries=()` → `memory_section=None`; no `memory://ant/context` source
- Build with 3 entries → `memory_section.returned_count=3`; `record_ids` correct; `record_types` parallel
- Entries order [A,B] → different digest from [B,A]
- Tags different input order → same digest (sorted)
- Same entries → same digest
- `memory_context.txt` content = entries joined with separator
- `store.load()` returns LoadedSource including `memory://ant/context`
- Reopen old package (no memory_entries key) → no error
- Backward compat: existing context tests pass
- `MemoryContextSection` all fields typed; no free-form string

**Gate**: targeted + cross-layer regression (`pytest tests/test_context_*.py -v`).
**Dependency**: CP3.
**Commit**: `feat(phase7-cp4): context-memory DTO, canonical digest, store integration, structured manifest`

---

### CP5 — Workflow Wiring Vertical Slice

**Mục tiêu**: Wire `ContextPreparationInput.memory_criteria` → `ContextSourcePreparerImpl` →
`SearchMemory` → `MemoryContextEntry` selection → `ContextBuildRequest` → actual workflow execution.

**CP5 owns runtime wiring only.**

**Files**:
```
application/ports/context_preparation.py — ADD memory_criteria: MemorySearchCriteria | None = None
context/preparation.py      — UPDATE ContextSourcePreparerImpl: accept SearchMemory|None; if criteria → call search → apply budget selector → set memory_entries
src/ant_orchestrator/composition.py — NEW: WorkflowServices + build_workflow_services(); inject SearchMemory into ContextSourcePreparerImpl
cli/workflow_composition.py          — thin re-export wrapper
```

**Runtime chain**:
```
RunWorkflow.execute()
  → WorkflowDocumentationPreparer (for doc tasks)
  → ContextSourcePreparerImpl.prepare(ContextPreparationInput(memory_criteria=criteria))
  → SearchMemory.execute(MemorySearchRequest from criteria) [if criteria not None]
  → budget selector loop → tuple[MemoryContextEntry, ...]
  → ContextBuildRequest(memory_entries=entries)
  → ContextPackageBuilder.build()
  → ContextPackage with memory_entries
  → ContextPackageStore.persist() → writes memory_context.txt + updates canonical
```

**Default criteria** (set by `WorkflowDocumentationPreparer` for doc tasks):
`MemorySearchCriteria(task_id=TaskId(current_task_id), limit=MEMORY_DEFAULT_LIMIT)`
all other fields = None/(). No writer → empty result → `memory_section=None`. Integration test seeds records manually.

**Integration test** (`tests/test_phase7_workflow_memory_integration.py` — NEW):
1. Seed MemoryRecord for task T-1 via `memory_repository.append()`
2. Run workflow for T-1 (stub worker, tmp_path workspace)
3. Inspect persisted context package: `manifest.memory_section is not None`
4. `manifest.memory_section.record_ids` contains seeded record ID
5. `memory_context.txt` exists and readable
6. Digest changes when different records seeded
7. GraphState JSON-safe: `assert_json_safe(state)` passes (no MemoryRecord in state)
8. Import boundary: workflows/ not importing memory/ or SearchMemory service

**Full integration gate #1 after CP5**:
```
python -m scripts.quality.gate
```
(This runs ruff-lint/ruff-format/mypy/file-size/pytest once each — not twice.)

**Gate**: FULL (gate #1). **Dependency**: CP4.
**Commit**: `feat(phase7-cp5): wire memory retrieval into workflow context preparation`

---

### CP6 — CLI Surface

**Mục tiêu**: `ant logs` + `ant memory search`. Reuse services.

**Files**:
```
cli/phase7_commands.py       — NEW: logs, memory_search + register(app)
cli/main.py                  — ADD phase7_commands.register(app); ADD memory sub-app
cli/json_contract.py         — ADD logs_payload(), memory_search_payload()
cli/render.py                — ADD render_logs(), render_memory_results()
```

**`ant logs`**: default limit `LOG_DEFAULT_LIMIT`; max `LOG_MAX_LIMIT`; absent → None → default;
explicit `--limit 0` → exit `EXIT_USAGE`.
Output includes `has_more` and `corrupt_count` if `--json` (in JSON payload).

**`ant memory search`**: default limit `MEMORY_DEFAULT_LIMIT`; absent → None → default;
`--source SOURCE` exact; `--confidence LEVEL` validated; `--limit 0` → exit `EXIT_USAGE`.

**Tests** (`tests/test_cli_phase7_logs.py`, `tests/test_cli_phase7_memory.py`):
- logs: empty → exit 0; limit=5 from 10 → 5; filter task; `--json` has `has_more`, `corrupt_count`
- memory: no records → exit 0; type filter; source filter; confidence filter; tag ANY; limit; invalid → exit 2
- `--limit 0` → exit 2 (EXIT_USAGE) for both commands

**Gate**: targeted + Phase 4 CLI regression. **Dependency**: CP5.
**Commit**: `feat(phase7-cp6): CLI logs and memory search commands`

---

### CP7 — FastAPI Surface & Neutral Composition Root

**Mục tiêu**: `create_app(workspace)` factory; WorkflowRun/WorkerRun endpoint separation; neutral root.

**New dependency**: `fastapi>=0.115,<0.116`, `uvicorn>=0.32,<0.33` (add to pyproject.toml).
Verify with `pip check` after add.

**Files**:
```
pyproject.toml                                — ADD fastapi + uvicorn
src/ant_orchestrator/composition.py           — FINALIZE (may already exist from CP5/CP6)
src/ant_orchestrator/api/main.py              — NEW: create_app(), create_default_app()
src/ant_orchestrator/api/schemas.py           — NEW: Pydantic request/response models
src/ant_orchestrator/api/routes/tasks.py      — NEW: POST /tasks; POST /tasks/{task_id}/workflow-runs; GET /tasks/{task_id}
src/ant_orchestrator/api/routes/workflow_runs.py — NEW: GET /workflow-runs/{id}
src/ant_orchestrator/api/routes/worker_runs.py   — NEW: GET /worker-runs/{id}
src/ant_orchestrator/api/routes/logs.py       — NEW: GET /logs
cli/workflow_composition.py                   — BECOME thin re-export from composition.py
```

**`api/` never imports `cli/workflow_composition` directly.**

**`POST /tasks/{task_id}/workflow-runs` behavior**:
- Call `run_workflow.execute(task_id)` (same as CLI `ant run`)
- Terminal task → `WorkflowStateError` → 422
- Active run + RESUME → 200 with run status (may be `waiting_for_approval`)
- New run → 200 with outcome
- Approval interrupt → `{workflow_run_id, status: "waiting_for_approval", approval_id}`
- Blocking: wrap with `run_in_threadpool`

**`GET /worker-runs/{worker_run_id}`**: calls `GetWorkerRunDetail`. Includes energy.

**CLI/API parity test** (`tests/test_phase7_api_e2e.py`):
- Create via CLI → inspect via API → same task/status
- Create via API → inspect via CLI → same task
- `GET /logs` events visible via `ant logs` too

**Tests** (`tests/test_phase7_api.py`): all endpoints; error mapping; no traceback/secret in response;
`POST /tasks/{terminal_id}/workflow-runs` → 422; resume semantics for active run; `pip check` clean.

**Gate**: targeted + `pip check`. **Dependency**: CP6.
**Commit**: `feat(phase7-cp7): FastAPI surface, WorkflowRun/WorkerRun endpoints, neutral composition root`

---

### CP8 — Restart Recovery Evidence

**Mục tiêu**: 3-level restart evidence (app-instance / service reinit / real subprocess).

**Files**: only test files.

**Duplicate side effects assertions** (compare against baseline, not hard-code count):
```python
baseline_wf_runs = count_records("workflow_runs WHERE task_id = ?", task_id)
baseline_worker_runs = count_records("worker_runs WHERE task_id = ?", task_id)
baseline_attempts = count_records("execution_attempts WHERE run_id = ?", run_id)
baseline_approvals = count_records("approvals WHERE workflow_run_id = ?", run_id)
# ... restart ...
# After resume to terminal:
assert count("workflow_runs WHERE task_id=?", task_id) == baseline_wf_runs  # no new run
assert count("approvals WHERE workflow_run_id=?", run_id) == baseline_approvals  # no dup
# worker_runs and attempts may increase by expected semantics (retry = +1 attempt)
# compare against expected domain semantics, not blindly == 1
```

**Level 3 real subprocess**: actual `subprocess.run()` with CLI entry points on `tmp_path`.
Uses energy gate to trigger deterministic approval interrupt. Process A exits after checkpoint is
durable (`subprocess.run()` returns after `ant run` output is captured). Process B is a new
`subprocess.run()` invocation.

**Tests** (`tests/test_phase7_restart.py`):
- Level 1: app-instance (TestClient context manager close/reopen)
- Level 2: service reinit (build_workflow_services twice, same workspace)
- Level 3: real subprocess (subprocess.run CLI commands, two separate processes)
- All levels: status preserved; no duplicate WorkflowRun; approval record survives; resume works; audit trail continuous

**Gate**: targeted + Phase 4 recovery regression. **Dependency**: CP7.
**Commit**: `test(phase7-cp8): three-level restart recovery evidence`

---

### CP9 — Release Validation Gate

**Mục tiêu**: Full quality gate #2; Docker policy from source-of-truth; no duplicate pytest.

**Activities**:
1. `python -m scripts.quality.gate` — gate runs ruff-lint/ruff-format/mypy/file-size/pytest (once each per `scripts/quality/gate.py`). Pytest count from gate output — do NOT run pytest separately again.
2. Offline proof: grep source for live markers (`@pytest.mark.live_openai`, `@pytest.mark.live_ollama`); verify no new markers added without `pytest.ini` filter; no network fixture required since gate already runs all pytest.
3. Context manifest evidence: create WorkflowRun with seeded memory records → inspect `manifest.json` → verify `memory_section` populated → record as evidence
4. Docker policy per source-of-truth: `scripts/quality/gate.py` does NOT contain a Docker gate. No Docker gate exists in the current quality scripts. Evidence: read `scripts/quality/gate.py` GATES list. Therefore: **no mandatory Docker gate for Phase 7 closure**. If PO introduces a Docker gate in a future commit, revisit. Do NOT invent Docker-mandatory/optional classification not in the source-of-truth.
5. Create `docs/plans/PHASE_7_COMPLETION_REPORT.md` (after 5/5 PASS only)

**Gate**: FULL (gate #2 and final). **Dependency**: CP8.
**Commit**: `docs(phase7): Phase 7 completion evidence and report`

---

### CP10 — Closure

**Mục tiêu**: Completion audit; ROADMAP update.

**Activities**:
1. Read `PHASE_7_COMPLETION_REPORT.md`; verify all matrix rows have evidence
2. Requirement-evidence reconciliation: every F-matrix row has test PASS evidence
3. Secret/redaction audit: no API key, provider token, user content in artifacts
4. Working-tree audit: `git status` clean
5. ROADMAP.md: Phase 7 `NOT_STARTED` → `COMPLETED` with HEAD commit + date (only after CP9 PASS)

**Do NOT update ROADMAP before CP9 gate passes.**

**Commits** (separate):
```
docs(phase7): finalize Phase 7 closure audit trail
docs(roadmap): mark Phase 7 COMPLETED with closure evidence
```

---

## F. Requirement–Evidence Matrix

| Requirement | CP | Code path | Test | Failure mode |
|---|---|---|---|---|
| Filter by type (MemoryType) | CP2 | `type = ?` SQL | `test_filter_by_type` | Other type not excluded |
| Filter by task_id | CP1+CP2 | `task_id = ?` FK | `test_filter_by_task` | Wrong task returns rows |
| Filter by source (metadata) | CP2 | `source = ?` case-sens | `test_filter_by_source` | Case-insensitive match |
| Filter by confidence (metadata) | CP2 | `confidence = ?` | `test_filter_by_confidence` | Wrong confidence returned |
| Filter by tags ANY (SQL json_each) | CP2 | `json_each() WHERE IN` | `test_filter_by_tags_any` | Record missed beyond window |
| include_deprecated=False SQL | CP2 | `deprecated = 0` predicate | `test_filter_deprecated` | `deprecated = NULL` bug |
| Bounded limit, no dump | CP2 | SQL LIMIT | `test_no_dump` | limit=5 from 50 → >5 |
| Stable newest-first ordering | CP2 | `ORDER BY created_at DESC, id ASC` | `test_ordering_stable` | Non-deterministic |
| Cross-workspace isolation | CP1+CP2 | Separate DB files | `test_cross_workspace` | Records leak |
| MemorySearchCriteria correct layer | CP2 | `core/domain/query.py` | `test_import_boundary.py` | Import violation |
| SQLite JSON1 check (injectable) | CP1 | `_verify_json1()` | `test_json1_capability` | Silent fallback |
| JSON1 failure → fail-fast | CP1 | `StorageIntegrityError` raised | `test_json1_failure_path` | No exception raised |
| No production MemoryRecord writer | Audit | No append() in application/ | Code review | Implicit writer assumed |
| SearchMemory depends on port | CP3 | `MemoryRepository` Protocol | `test_import_boundary.py` | Concrete import |
| AuditLogReader port wired | CP3 | `GetTaskLogs(AuditLogReader)` | `test_get_task_logs` | Direct JSONL read |
| AuditLogPage has_more not is_partial | CP3 | `AuditLogPage.has_more` | `test_log_page_has_more` | Bool confusion |
| Newest-first log events | CP3 | Reverse-within-file algo | `test_newest_first_events` | 5 oldest returned instead |
| Corrupt JSONL line handling | CP3 | skip + corrupt_count | `test_corrupt_line` | Exception on corrupt |
| MemoryContextEntry single DTO | CP4 | `context/package.py` | Code review | Multiple representations |
| Context digest record-order sensitive | CP4 | `canonical["memory_entries"]` order | `test_digest_order_sensitive` | Order change = no digest change |
| Context digest tag-sort stable | CP4 | sorted tags in to_canonical | `test_digest_tag_order` | Different input order = diff digest |
| Memory budget (skip behavior) | CP4 | `BudgetTracker.can_fit()` per entry | `test_budget_skip_behavior` | Over-budget entry crashes |
| Store writes memory as source | CP4 | `sources/memory_context.txt` | `test_store_memory_source` | File not written |
| Reopen old package (no memory key) | CP4 | canonical["memory_entries"] absent → [] | `test_reopen_old_package` | KeyError raised |
| MemoryContextSection structured | CP4 | Typed fields; no filter_summary str | `test_memory_section_fields` | Free-form str used |
| Workflow wiring (actual execution) | CP5 | ContextSourcePreparerImpl + SearchMemory | `test_workflow_memory_integration` | memory_section absent |
| GraphState JSON-safe | CP5 | `assert_json_safe(state)` | `test_workflow_memory_integration` | GraphStateError |
| CLI ant logs | CP6 | GetTaskLogs | `test_cli_phase7_logs` | Invalid limit → exit 0 |
| CLI ant memory search (all filters) | CP6 | SearchMemory | `test_cli_phase7_memory` | Invalid type → exit 0 |
| CLI log JSON has has_more/corrupt | CP6 | logs_payload() | `test_cli_logs_json_metadata` | Metadata stripped |
| API WorkflowRun vs WorkerRun separated | CP7 | /workflow-runs/ vs /worker-runs/ | `test_api_resource_model` | Ambiguous /runs/{id} |
| POST /tasks/{id}/workflow-runs resume | CP7 | RunWorkflow.execute() → _handle_existing | `test_api_resume_active` | 409 returned instead |
| POST /tasks/{terminal}/workflow-runs → 422 | CP7 | WorkflowStateError → 422 | `test_api_terminal_task` | 409/201 returned |
| create_app(workspace) factory | CP7 | `TestClient(create_app(tmp_path))` | `test_phase7_api` | Global cwd contamination |
| Neutral composition root | CP7 | api/ not import cli/ | `test_import_boundary.py` | CLI import from api |
| Energy visibility (task detail) | CP7 | EnergyUsage in TaskDetailView | `test_api_energy_visible` | Energy absent |
| Approval visibility (task detail) | CP7 | Approval in TaskDetailView | `test_api_approval_visible` | Approval absent |
| Worker-run energy | CP7 | EnergyUsage in WorkerRunDetailView | `test_api_worker_run_energy` | Energy absent |
| CLI/API parity | CP7 | same state.sqlite | `test_phase7_api_e2e` | Status mismatch |
| App-instance restart | CP8 | TestClient open/close/open | `test_app_instance_restart` | State not persisted |
| Service reinit restart | CP8 | build_workflow_services twice | `test_service_reinit` | State not found |
| Real subprocess restart | CP8 | subprocess.run CLI commands | `test_real_subprocess_restart` | State lost across processes |
| No duplicate WorkflowRun after restart | CP8 | count baseline compare | `test_no_dup_workflow_run` | Duplicate created |
| Approval record survives restart | CP8 | count baseline compare | `test_no_dup_approval` | Dup or lost |
| Audit trail continuous after restart | CP8 | JSONL on disk | `test_audit_trail_restart` | Events missing |
| Migration chain v1→v4 | CP1 | Full chain test | `test_full_migration_chain` | Intermediate fail |
| Full quality gate | CP9 | `scripts.quality.gate` 5/5 | gate output | Any gate fail |
| Offline tests (no live markers) | CP9 | grep markers; gate runs all pytest | gate output | Live call in mandatory |

---

## G. Quality Gate Cadence

**Two full integration gates only:**

| CP | Gate | Source |
|---|---|---|
| CP5 (Workflow Wiring) | `python -m scripts.quality.gate` (FULL #1) | Verifies whole memory-to-context chain |
| CP9 (Release Validation) | `python -m scripts.quality.gate` (FULL #2) | Closure condition |

**Pytest runs once inside each gate** (per `scripts/quality/gate.py` GATES list). No additional
standalone `pytest` invocation at CP9.

**Offline proof**: marker grep + gate output (no separate `pytest -m "not live_openai"` run needed).

**All other CPs: targeted only:**

| CP | Command |
|---|---|
| CP0 | `pytest tests/test_config.py -v` |
| CP1 | `pytest tests/test_migration_v4.py tests/test_repositories_records.py -v` |
| CP2 | `pytest tests/test_phase7_memory_retrieval.py tests/test_import_boundary.py -v` |
| CP3 | `pytest tests/test_phase7_query_services.py -v` |
| CP4 | `pytest tests/test_phase7_context_memory.py tests/test_context_*.py -v` |
| CP6 | `pytest tests/test_cli_phase7*.py tests/test_cli_cp7_*.py -v` |
| CP7 | `pytest tests/test_phase7_api.py tests/test_phase7_api_e2e.py -v && pip check` |
| CP8 | `pytest tests/test_phase7_restart.py tests/test_cp8_recovery.py -v` |

---

## H. Risks

| Rủi ro | Khả năng | Biện pháp |
|---|---|---|
| ContextBuildRequest/Manifest change breaks existing tests | Trung bình | Default empty/None fields; trace callers before CP4 |
| FastAPI/Pydantic conflict với litellm/langgraph | Thấp-trung | `pip check` tại CP7; upper bound versions |
| JSON1 not available in some exotic env | Rất thấp | Fail-fast check; injectable for testability |
| context/package.py exceeds 350 lines | Thấp | Split MemoryContextEntry to `context/memory_entry.py` if needed |
| Budget skip semantics misunderstood | Thấp | Explicit skip test; not truncate, not stop |
| Level 3 subprocess test flaky in CI | Thấp | Use deterministic energy gate; tmp_path isolation |

---

## I. Pre-Coding Checklist (per checkpoint)

1. Đọc đầy đủ file interface, implementation, callers, serializers liên quan
2. Trace import boundary: không vi phạm `test_import_boundary.py` constraints
3. Verify file size ≤ 350 lines after change (split if needed)
4. No magic number: all constants from `config/constants.py`
5. No SQL in CLI command or API route handler
6. No business logic in CLI command or API route handler
7. `MemoryRecord` and domain objects never placed in `GraphState` TypedDict
8. Run targeted test after each sub-step

---

## J. Final Verdict

`PHASE 7 PLANNING REVISION 2: READY FOR REVIEW`

**Baseline**: branch `develop`, HEAD `96ee8e4`, working tree clean, Phase 6 COMPLETED.

**Plan covers**: all 19 original blockers + 19 additional corrections fully addressed;
CP0–CP10 with scope/acceptance criteria; WorkflowRun/WorkerRun separated in API;
newest-first AuditLogReader algorithm correct; AuditLogPage metadata preserved;
MemoryContextEntry as single canonical representation; digest record-order preserving;
structured MemoryContextSection; limit=None sentinel-free; include_deprecated SQL correct;
MemoryRecord writers audited (no production writer in Phase 7); RunWorkflow active-run
RESUME semantics reflected in API; energy + approval visibility explicit; CP4/CP5 boundary
clean; 3-level restart with real subprocess; duplicate side effect assertions against baseline;
pytest runs once inside quality gate at CP9; Docker policy grounded in `scripts/quality/gate.py`
(no Docker gate exists); JSON1 test inconsistency resolved via injectable checker; 2 full gates.

**Single file changed**: `docs/plans/PHASE_7_IMPLEMENTATION_PLAN.md` (this file).
**No changes**: source, tests, dependencies, ROADMAP, Foundation, ADR, completion reports, Git.
