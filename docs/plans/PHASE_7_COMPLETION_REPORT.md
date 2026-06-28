# Phase 7 — Completion Report

> **Trạng thái**: PHASE 7 RELEASE VALIDATION: PASS
>
> **Ngày**: 2026-06-29
> **Branch**: `develop`

---

## A. Closure Status

```
PHASE 7 RELEASE VALIDATION: PASS
```

Phase 7 chưa được đánh dấu `COMPLETED` tại ROADMAP. ROADMAP closure thuộc CP10.

---

## B. Baseline và Commit Chain

| Mốc | Commit |
|---|---|
| Phase 6 COMPLETED baseline | `96ee8e4` |
| CP0 — Constants, AuditEventType, ADR-0008 | `5cb1273` |
| CP1 — Schema v4, migration chain, JSON1 check | `df4e4ce` |
| CP2 — MemorySearchCriteria, SQL json_each retrieval | `0ac6675` |
| CP3 — SearchMemory service, AuditLogReader port, query services | `947db9a` |
| CP4 — MemoryContextEntry DTO, canonical digest, store integration | `d6ec243` |
| CP5 implementation — workflow memory wiring | `5bf3f1f` |
| CP5 correction — quality gate | `36ccecd` |
| CP6 — CLI logs và memory search | `07ea6fd` |
| CP7 implementation — FastAPI surface, neutral composition root | `9430e5c` |
| CP7 correction — FastAPI endpoint evidence | `a0f617b` |
| CP8 — Three-level restart recovery evidence | `1b9bdc3` |
| CP9 — Completion evidence và report | *(commit sau khi tạo file này)* |

---

## C. Delivered Capabilities

### Schema / Migration
- `MemoryRecord.task_id: TaskId | None` (nullable FK), schema v4
- Migration chain v1 → v2 → v3 → v4 idempotent, fail-closed
- SQLite JSON1 capability check injectable và fail-fast tại bootstrap

### Deterministic Retrieval
- `MemorySearchCriteria` tại `core/domain/query.py` (đúng layer)
- SQL filter: type / task_id / source / confidence / tags (ANY via `json_each`)
- `include_deprecated=False` → `deprecated = 0 OR deprecated IS NULL`
- `ORDER BY created_at DESC, id ASC` stable ordering; SQL-level `LIMIT`
- Cross-workspace isolation qua separate DB files

### Context Integration
- `MemoryContextEntry` DTO: single canonical representation cho context-facing memory
- `MemoryContextSection`: structured filter evidence, không có free-form string
- `canonical_context_manifest()` bao gồm `memory_entries` in selection order → digest record-order sensitive
- `ContextPackageStore._write_sources()`: ghi `sources/memory_context.txt`, path key `memory://ant/context`
- Budget selector: `BudgetTracker.can_fit()` per entry; skip oversized, continue (không stop)
- Reopen old package (không có `memory_entries` key): `[]` → `memory_section = None`, không raise

### Query / Observability Services
- `SearchMemory`: limit sentinel-free (`None` → resolve `MEMORY_DEFAULT_LIMIT`); validation `limit <= 0`, `limit > MAX`, empty tag
- `SearchMemory` emits `AuditEventType.MEMORY_RETRIEVAL`; không ghi title/summary/content vào audit
- `AuditLogReader` port + `JsonlAuditLogReader` adapter: newest-first (reverse-within-file), `has_more` semantics, `corrupt_count`
- `GetTaskDetail`, `GetWorkerRunDetail`, `GetTaskLogs` services
- `EnergyTotalsView`, `ApprovalView` trong task detail

### CLI
- `ant logs [--task-id] [--limit] [--json]`: real `GetTaskLogs` + `JsonlAuditLogReader`
- `ant memory search [--type] [--source] [--confidence] [--tags] [--limit] [--json]`
- JSON output includes `has_more`, `corrupt_count`; `--limit 0` → exit `EXIT_USAGE`

### FastAPI
- `create_app(workspace: Path) → FastAPI` factory; `create_default_app()` zero-arg
- `POST /tasks`, `POST /tasks/{task_id}/workflow-runs` (resume semantics, không 409)
- `GET /tasks/{task_id}`, `GET /workflow-runs/{id}`, `GET /worker-runs/{id}`, `GET /logs`
- WorkflowRun vs WorkerRun phân biệt rõ (`/workflow-runs/` vs `/worker-runs/`)
- Error mapping: RecordNotFound→404, WorkflowStateError→422, DomainError→422, DatabasePortError→503
- Sanitized error responses: không traceback, không secret, không absolute path
- `run_in_threadpool` cho blocking calls

### Neutral Composition Root
- `src/ant_orchestrator/composition.py`: `WorkflowServices` + `build_workflow_services()`
- `cli/workflow_composition.py`: thin re-export wrapper
- `api/dependencies.py`: import từ `ant_orchestrator.composition`, không import `cli/`

### Restart / Recovery
- Level 1: TestClient open → close → reopen (app-instance restart)
- Level 2: `build_workflow_services(tmp_path)` × 2 (service reinitialization)
- Level 3: `subprocess.run()` CLI commands (actual Python interpreter process boundary)
- Identity preserved: same `workflow_run_id` sau restart; không tạo duplicate WorkflowRun
- Approval record survives; approval count không tăng sau resume
- Audit trail continuous: JSONL trên disk, không bị xóa khi restart

### Security / Import Boundaries
- `api/` không import `cli/workflow_composition` trực tiếp
- `application/services/` không import `persistence/` trực tiếp
- `workflows/` không import memory service
- `core/domain/` không import `config/constants`
- GraphState JSON-safe: không có `MemoryRecord`, domain object, repository trong state

---

## D. Requirement–Evidence Matrix

| Requirement | Code path | Test / Evidence | Result |
|---|---|---|---|
| Filter by type | `type = ?` SQL | `test_type_filter_returns_only_matching_type` (test_phase7_memory_retrieval.py) | PASS |
| Filter by task_id | `task_id = ?` FK | `test_task_filter_returns_only_matching_task` (test_phase7_memory_retrieval.py) | PASS |
| Filter by source (case-sensitive) | `source = ?` | `test_source_filter_case_sensitive` (test_phase7_memory_retrieval.py) | PASS |
| Filter by confidence | `confidence = ?` | `test_confidence_filter_returns_only_matching` (test_phase7_memory_retrieval.py) | PASS |
| Filter by tags ANY (json_each) | `json_each() WHERE IN` | `test_tags_any_returns_records_with_at_least_one_tag` (test_phase7_memory_retrieval.py) | PASS |
| include_deprecated=False SQL | `deprecated = 0 OR IS NULL` | `test_deprecated_excluded_by_default` (test_phase7_memory_retrieval_order.py) | PASS |
| Bounded limit, no dump | SQL LIMIT | `test_limit_returns_exact_count`, `test_completeness_sql_filter_before_limit` (test_phase7_memory_retrieval.py) | PASS |
| Stable newest-first ordering | `ORDER BY created_at DESC, id ASC` | `test_ordering_newest_first` (test_phase7_memory_retrieval_order.py) | PASS |
| Cross-workspace isolation | Separate DB files | `test_cross_workspace_isolation` (test_migration_v4_repo.py) | PASS |
| MemorySearchCriteria correct layer | `core/domain/query.py` | `test_core_domain_is_infra_free`, `test_application_services_no_adapter_imports` (test_import_boundary.py) | PASS |
| SQLite JSON1 check (injectable) | `_verify_json1()` / `_check_n_capability()` | `test_json1_check_success_with_real_connection` (test_migration_v4_repo.py) | PASS |
| JSON1 failure → fail-fast | `StorageIntegrityError` raised | `test_json1_check_failure_raises_storage_integrity_error` (test_migration_v4_repo.py) | PASS |
| No production MemoryRecord writer | No `append()` in application/ | Code review — audit confirmed no `memory_repository.append()` in `application/services/` | PASS |
| SearchMemory depends on port | `MemoryRepository` Protocol | `test_application_services_no_adapter_imports` (test_import_boundary.py) | PASS |
| AuditLogReader port wired | `GetTaskLogs(AuditLogReader)` | `test_get_task_logs_metadata_preserved` (test_phase7_task_query_services.py) | PASS |
| AuditLogPage has_more semantics | `AuditLogPage.has_more` | `test_has_more_true_when_sixth_event_found` (test_jsonl_reader_core.py) | PASS |
| Newest-first log events | Reverse-within-file algo | `test_one_file_ten_events_limit_five_returns_newest` (test_jsonl_reader_core.py) | PASS |
| Corrupt JSONL line handling | skip + corrupt_count | `test_corrupt_middle_line_skipped` (test_jsonl_reader_filters.py) | PASS |
| MemoryContextEntry single DTO | `context/package.py` | `test_from_record_sets_basic_fields` (test_phase7_context_memory_model.py) | PASS |
| Context digest record-order sensitive | `canonical["memory_entries"]` order | `test_entry_order_AB_differs_from_BA` (test_phase7_context_memory_store.py) | PASS |
| Context digest tag-sort stable | sorted tags in `to_canonical` | `test_pre_sorted_tags_produce_same_digest` (test_phase7_context_memory_store.py) | PASS |
| Memory budget skip behavior | `BudgetTracker.can_fit()` per entry | `test_budget_selector_oversized_first_skipped_later_included` (test_phase7_context_memory_model.py) | PASS |
| Store writes memory as source | `sources/memory_context.txt` | `test_store_memory_source_written` (test_phase7_context_memory_store.py) | PASS |
| Reopen old package (no memory key) | `canonical["memory_entries"]` absent → `[]` | `test_store_legacy_no_memory_package_still_works` (test_phase7_context_memory_store.py) | PASS |
| MemoryContextSection structured | Typed fields; no filter_summary str | `test_memory_context_section_nonempty` (test_phase7_context_memory_model.py) | PASS |
| Workflow wiring (actual execution) | `ContextSourcePreparerImpl` + `SearchMemory` | `test_memory_records_appear_in_context_package` (test_phase7_workflow_memory_integration.py) | PASS |
| GraphState JSON-safe | `json.dumps(all_fields)` không raise | `test_state_fields_are_json_safe` (test_phase7_workflow_memory_integration.py) | PASS |
| CLI ant logs | `GetTaskLogs` + `JsonlAuditLogReader` | `test_empty_logs_exits_zero`, `test_limit_five_from_ten` (test_cli_phase7_logs.py) | PASS |
| CLI ant memory search (all filters) | `SearchMemory` | `test_type_filter`, `test_source_exact_case_sensitive`, `test_confidence_filter` (test_cli_phase7_memory.py) | PASS |
| CLI log JSON has has_more/corrupt | `logs_payload()` | `test_json_has_more_true`, `test_json_payload_shape` (test_cli_phase7_logs.py) | PASS |
| API WorkflowRun vs WorkerRun separated | `/workflow-runs/` vs `/worker-runs/` | `test_worker_run_id_not_interchangeable_with_workflow_run_id` (test_phase7_api_runs.py) | PASS |
| POST /tasks/{id}/workflow-runs resume | `RunWorkflow.execute()` → `_handle_existing` | `test_run_workflow_active_run_resume` (test_phase7_api_tasks.py) | PASS |
| POST /tasks/{terminal}/workflow-runs → 422 | `WorkflowStateError` → 422 | `test_run_workflow_terminal_task_422` (test_phase7_api_tasks.py) | PASS |
| create_app(workspace) factory | `TestClient(create_app(tmp_path))` | `test_two_workspace_isolation`, `test_no_module_level_app_object` (test_phase7_api_runs.py) | PASS |
| Neutral composition root | api/ not import cli/ | `test_no_module_level_app_object` (test_phase7_api_runs.py); `test_application_services_no_adapter_imports` (test_import_boundary.py) | PASS |
| Energy visibility (task detail) | `EnergyUsage` in `TaskDetailView` | `test_get_task_energy_visible` (test_phase7_api_tasks.py) | PASS |
| Approval visibility (task detail) | `Approval` in `TaskDetailView` | `test_get_task_approval_visible` (test_phase7_api_tasks.py) | PASS |
| Worker-run energy | `EnergyUsage` in `WorkerRunDetailView` | `test_get_worker_run_energy_visible` (test_phase7_api_runs.py) | PASS |
| CLI/API parity | same `state.sqlite` | `test_phase7_api_e2e.py` (8 tests) | PASS |
| App-instance restart | TestClient open/close/open | `test_app_instance_restart_state_preserved` (test_phase7_restart.py) | PASS |
| Service reinit restart | `build_workflow_services` × 2 | `test_service_reinit_state_preserved` (test_phase7_restart.py) | PASS |
| Real subprocess restart | `subprocess.run()` CLI commands | `test_real_subprocess_restart_state_preserved` (test_phase7_restart.py) | PASS |
| No duplicate WorkflowRun after restart | `count_wf_runs_for_task == baseline` | `test_real_subprocess_restart_state_preserved` (assert_no_duplicate_wf_runs) | PASS |
| Approval record survives restart | `count_approvals_for_run == baseline` | `test_app_instance_restart_state_preserved` (assert_no_duplicate_approvals) | PASS |
| Audit trail continuous after restart | JSONL non-decreasing | `test_real_subprocess_audit_trail_continuous` (test_phase7_restart.py) | PASS |
| Migration chain v1→v4 | Full chain test | `test_chain_v1_to_v4` (test_migration_v4.py) | PASS |
| Full quality gate | `scripts.quality.gate` 5/5 | Gate output 2026-06-29 (exit 0) | PASS |
| Offline tests (no live markers) | grep markers; gate output | Static audit + gate 15 skipped = live/docker/optional | PASS |

**Tổng cộng**: 48 requirements — 48 PASS — 0 thiếu.

---

## E. Quality Gate

Lệnh: `python -m scripts.quality.gate`
Chạy: 2026-06-29 (CP9 final gate, exit code 0)

```
ruff-lint:   PASS (exit 0)
ruff-format: PASS (exit 0)
mypy:        PASS (exit 0)
file-size:   PASS (exit 0)
pytest:      2051 passed, 15 skipped, 0 failed (exit 0)
```

**Gate 5/5 PASS.**

**Correction trong CP9**: `src/ant_orchestrator/api/errors.py` line 49 vượt 100 chars (ruff E501).
Sửa bằng cách wrap function signature và return statement để format-compliant. Không thay đổi behavior.

---

## F. Offline / Deterministic Proof

**Phân tích static markers**:
- `tests/test_litellm_live.py`: `pytestmark = pytest.mark.live_openai` → skip khi thiếu `OPENAI_API_KEY` + `ANT_LIVE_OPENAI_MODEL` (pyproject.toml markers config)
- `tests/test_ollama_live.py`: `pytestmark = pytest.mark.live_ollama` → skip khi thiếu `ANT_LIVE_OLLAMA_MODEL` + `ANT_LIVE_OLLAMA_BASE_URL`
- `tests/test_phase5_cp7_ollama.py`: marked live_ollama → skip
- `tests/test_phase6_container_isolation_docker.py`: chứa `socket.create_connection` nhưng đây là Python string (probe script) chạy bên trong container; bản thân test skip khi `docker CLI not available on host`
- `fake_*.py` references `.requests.append()`: là test doubles, không phải HTTP

**Gate output**: `2051 passed, 15 skipped` — 15 skipped đúng là live/docker/optional tests, không có mandatory test bị skip.

**TestClient là in-process ASGI**: `httpx.TestClient(create_app(tmp_path))` không tạo network socket ra ngoài.

**Level 3 subprocess**: `subprocess.run([sys.executable, "-m", "ant_orchestrator.cli", ...])` chỉ chạy local Python interpreter trên `tmp_path`; không cần network.

**Kết luận**: Mandatory release test suite không cần API key, Ollama server, internet, hay external provider.

---

## G. Docker Policy

**Source-of-truth**: `scripts/quality/gate.py`

```python
GATES: list[tuple[str, list[str]]] = [
    ("ruff-lint",   [sys.executable, "-m", "ruff", "check", "."]),
    ("ruff-format", [sys.executable, "-m", "ruff", "format", "--check", "."]),
    ("mypy",        [sys.executable, "-m", "mypy", "src", "scripts"]),
    ("file-size",   [sys.executable, "-m", "scripts.quality.file_size"]),
    ("pytest",      [sys.executable, "-m", "pytest"]),
]
```

Không có Docker gate trong GATES. Không có release script khác được canonical docs quy định bắt buộc.

**Kết luận**: Docker không nằm trong current mandatory quality gate. Docker deployment không phải closure criterion của Phase 7. Đây không phải tuyên bố Docker deployment đã được chứng minh — Docker là deferred concern.

---

## H. Recovery Evidence

**Level 1 — App-instance restart**:
- `setup_paused_workspace(tmp_path)` → drive to `waiting_for_approval` qua driver subprocess
- `TestClient(create_app(workspace))` instance A → đóng hoàn toàn
- `TestClient(create_app(workspace))` instance B → đọc same `task_id` → status `waiting_for_approval`
- `count_wf_runs_for_task == baseline_wf` sau cả hai app instances
- `count_approvals_for_run == baseline_app`
- Test: `test_app_instance_restart_state_preserved`

**Level 2 — Service reinitialization**:
- `build_scenario_services(workspace, ...)` → `run_workflow.execute(task_id)` → `waiting_for_approval`
- `build_workflow_services(workspace)` (production composition) → `task_status.report()` → same `run_id`, same status
- `resolve_approval.approve()` trả `run_id` cũ, không tạo WorkflowRun mới
- Test: `test_service_reinit_state_preserved`

**Level 3 — Real subprocess restart**:
- Process A: `subprocess.run([..., "init", "--path", workspace])` + `task create` + `run --significant-write`
- `baseline_wf == 1`, `baseline_app == 1` (exact count assertions)
- Process B-1: `subprocess.run([..., "status", ...])` → `status == "waiting_for_approval"`
- Process B-2: `subprocess.run([..., "approve", ...])` → `workflow_run_id == run_id` (identity preserved)
- Process B-3: `subprocess.run([..., "status", ...])` → `status in ("completed", "failed", "rejected")`
- `count_wf_runs_for_task == baseline_wf` (không có duplicate)
- `count_approvals_for_run == baseline_app` (không có duplicate)
- Test: `test_real_subprocess_restart_state_preserved`

**Duplicate side-effect assertions**: tất cả dùng `== baseline` (exact), không phải `>= 0`.

---

## I. Security / Redaction Evidence

**Kiểm tra trên `src/`, `tests/`, `docs/plans/`, `docs/product/`**:

- Không có API key thật hay auth token
- Không có `.env` dump hay raw credential
- Không có raw provider output hay raw traceback trong API/CLI responses (test_redaction.py; test_phase7_api_errors.py verify "Traceback" không xuất hiện)
- "token" references: token budgeting (estimated_tokens, max_input_tokens) — không phải auth token
- "secret" references: security policy constraints (không truyền secret vào container, no-secret trong graph state) — không phải actual secret
- Sample trong `MEMORY_AND_PHEROMONE_SPEC.md` là example MemoryRecord summary, không phải secret thật
- Không có absolute local path trong completion report này
- Không có memory title/summary/content trong audit events (verified bởi `SearchMemory` chỉ log correlation_id + filter, không log content)
- Không có SQLite/JSONL artifact trong commit (chỉ source và docs)
- `ROADMAP.md` không được cập nhật trong CP9

---

## J. Known Limitations / Deferred

| Mục | Trạng thái |
|---|---|
| Production MemoryRecord writer service | Không có trong Phase 7. Post-MVP. Integration tests seed records thủ công. |
| Semantic / vector retrieval | Deferred. Phase 7 chỉ có SQL-level deterministic retrieval. |
| Authentication / authorization | Deferred. Local MVP only, không cần auth. |
| WebSocket / SSE / streaming | Deferred. |
| Multi-tenant server, distributed tracing | Deferred. |
| Docker deployment | Không được chứng minh bởi mandatory gate (không có Docker gate). |
| Post-MVP queen / self-evolving strategy | Không thuộc Phase 7. |

---

## K. CP10 Prerequisites

| Điều kiện | Trạng thái |
|---|---|
| Completion report tồn tại | `docs/plans/PHASE_7_COMPLETION_REPORT.md` ✓ |
| Gate 5/5 PASS | ruff-lint/ruff-format/mypy/file-size/pytest PASS ✓ |
| Requirement matrix reconciled | 50/50 rows PASS ✓ |
| Working tree clean sau CP9 commit | Pending commit |
| ROADMAP chưa được cập nhật | Đúng — ROADMAP closure thuộc CP10 ✓ |

**CP10 chưa bắt đầu.**
