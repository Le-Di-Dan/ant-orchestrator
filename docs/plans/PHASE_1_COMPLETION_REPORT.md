# Phase 1 — Completion Report

Ngày: 2026-06-24
Kết quả audit: **PASS**
Tham chiếu kế hoạch: `docs/plans/PHASE_1_PLAN.md`

---

## 1. Tóm tắt

Phase 1 (Core Domain, Config, Workspace & Minimal State Persistence) đã hoàn tất theo 8 checkpoint của plan. Domain thuần Python + config typed + workspace `.ant/` (atomic, idempotent, sống qua git-clone) + SQLite persistence (repository pattern) + CLI mỏng (`init`/`status`/`config show`) đều hoạt động và được kiểm chứng tự động.

- Module nguồn: 65 file trong `src/ant_orchestrator/` (sau khi xóa 2 file adapter error cũ).
- Test: **128 passed** (bao gồm 4 import-boundary AST tests).
- File lớn nhất: `persistence/schema.py` (185 dòng) — dưới giới hạn 350 (COD-004).
- Dependency mới duy nhất: `pyyaml` (runtime) + `types-pyyaml` (dev) — theo D10/D16 (config.yaml frozen).

## 2. Evidence quality gate

`python -m scripts.quality.gate` → **5/5 PASS**:

| Gate | Kết quả |
|---|---|
| ruff-lint | PASS (exit 0) |
| ruff-format | PASS (exit 0) |
| mypy (`src scripts`, strict) | PASS (exit 0) |
| file-size (≤350) | PASS (exit 0) |
| pytest | PASS — 128 passed |

Smoke test CLI thật (`ant`) trong thư mục tạm:
- `ant init` → "Initialised new Nest" (exit 0); chạy lại → "Nest already initialised" (exit 0, idempotent).
- `ant status` → `State: ready`, format version 1, schema version 1 (exit 0).
- `ant config show` → `version: 1`, `project.name: <dir>` (exit 0).
- `.ant/` layout đầy đủ; `.ant/.gitignore` đúng safety-first policy (D18).

Exit codes lỗi (CLI E2E):
- No nest → `status` / `config show`: **exit 3** ✓
- Workspace malformed (marker thiếu): **exit 3** ✓
- Database corrupted: **exit 4** ✓
- Schema version mới hơn: **exit 4** ✓

## 3. Definition of Done (đối chiếu §21 plan)

| # | Tiêu chí | Evidence |
|---|---|---|
| 1 | `ant init` ABSENT→CREATED, CONFIGURED(clone)→PROVISIONED, READY→ALREADY_INITIALIZED, CORRUPTED/INCOMPATIBLE/nested→error đúng exit | `test_application_init.py`, `test_cli_phase1.py` |
| 2 | Task/WorkerRun lifecycle; EnergyUsage append/read + ownership | `test_repositories_entities.py` |
| 3 | Checkpoint canonical-stable; Approval add/resolve resolve-once | `test_repositories_entities.py` |
| 4 | Evidence/Handoff/Pheromone append/read; Memory deprecate | `test_repositories_records.py` |
| 5 | Config typed, YAML safe-load, precedence, unknown-key reject mọi cấp | `test_config.py` |
| 6 | `core/domain`+`core/ports`+`application/ports` infra-free; **`application/services` không import workspace/persistence** (AST) | `test_import_boundary.py` (4 tests) |
| 7 | CLI delivery adapter, exit codes 0/1/2/3/4 | `test_cli_phase1.py`, `cli/exit_codes.py` |
| 8 | Bootstrap empty/partial/version> + CHECK + integrity-verified | `test_persistence_database.py` |
| 9 | Chỉ thêm PyYAML | `pyproject.toml` |
| 10 | Không file >350 dòng | file-size gate |
| 11 | Hằng số layout/version tập trung (`workspace/layout.py`, `config/constants.py`, `persistence/schema.py`) | review |
| 12 | Bao phủ happy + failure | toàn bộ test |
| 13 | Gate 5/5 PASS | §2 |
| 14 | Path qua `pathlib`; test trên dev OS (Windows). Không tuyên bố đa nền tảng | ghi chú |
| 15 | Báo cáo này tồn tại | file này |

## 4. Checkpoint đã hoàn tất

CP1 domain primitives/state model · CP2 records + repository ports + application ports · CP3 typed config · CP4 SQLite foundation/inspection/schema v1 · CP5 workspace lifecycle · CP6 SQLite repositories · CP7 application services + NestState + CLI + import boundary · CP8 closure (báo cáo này).

## 5. Quyết định kiến trúc đã hiện thực hoá

Layer layout `core/{domain,ports}` + `application/{ports,services,models}` + `config` + `workspace` + `persistence` + `cli` (D01–D04, D29); state split `WorkspaceArtifactState`/`DatabaseState`/`NestState` (D30); Approval immutable resolve-once (D31); `TaskStatus.rejected` terminal (D32); checkpoint canonical JSON (D33); enum CHECK sinh từ domain (D19); migration `schema_migrations` forward-only (D20); error taxonomy port-owned + `AntError` neutral (D23, D34); nested Nest cấm (D14, PO APPROVED); git safety policy (D18, PO APPROVED).

## 5b. Deviation và PO review

### F1 — Vị trí state enums — **PO APPROVED** (2026-06-24)

`WorkspaceArtifactState` và `DatabaseState` được đặt trong `application/ports/{workspace,database}.py` (port contract) thay vì `workspace/state.py` / `persistence/state.py` như §10.1 ban đầu. Lý do bắt buộc về layering: port `classify() → WorkspaceArtifactState` cần enum hiển thị cho `application/ports`, mà layer này không được import `workspace`/`persistence`. PO duyệt cập nhật §10.1. Không cần sửa code.

### F2 — Port-owned error contracts — **PO DIRECTED REFACTOR** (2026-06-24)

PO không chấp thuận `application/services` import trực tiếp `workspace.errors`/`persistence.errors`. Đã refactor:

- Error classes chuyển sang `application/ports/workspace.py` (`WorkspacePortError` base + 5 subclasses) và `application/ports/database.py` (`DatabasePortError` base + 3 subclasses).
- `workspace/errors.py` và `persistence/errors.py` đã **xóa** (không duy trì hai cây exception trùng nghĩa).
- Workspace adapter và persistence adapter import errors từ `application/ports` (cùng hướng dependency đã có cho state enums).
- AST import-boundary test mở rộng: test `application/services` không import `ant_orchestrator.workspace` hoặc `ant_orchestrator.persistence`.
- CLI `exit_codes.py` kiểm `isinstance(error, WorkspacePortError)` → exit 3, `isinstance(error, DatabasePortError)` → exit 4.

Dependency flow sau refactor:
```
application/services → application/ports (errors + state enums + protocols)
workspace adapter    → application/ports (errors + state enums)
persistence adapter  → application/ports (errors + state enums)
cli/exit_codes       → application/ports (error base classes)
```

`application/services` **TUYỆT ĐỐI KHÔNG** import `workspace` hoặc `persistence` — kiểm chứng bằng AST test.

## 6. Xác nhận phạm vi

Không có feature/dependency của phase sau (không LangGraph/LiteLLM/Ollama/provider adapter/worker/orchestration loop). Không transition validation (D28). Không retrieval/ranking memory (→P7). Domain không import sqlite3/yaml/typer (kiểm bằng AST). `ROADMAP.md` Phase 1 chuyển `NOT_STARTED` → `COMPLETED` kèm §14.
