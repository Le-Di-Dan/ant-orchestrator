# PHASE 8 — Workflow Integrity, Productization & NPM Distribution — Implementation Plan

> **Trạng thái plan**: `GOVERNANCE_FINAL — POST_PREFLIGHT_CORRECTIONS`
> **Loại task**: CANONICAL GOVERNANCE ARTIFACT — Phase 8 implementation guide.
> **Baseline xác nhận**: branch `phase/8-workflow-productization-npm`, HEAD `e372acb`, working tree README-only modified.
> Phase 7 `COMPLETED` — 2051 passed / 15 skipped / 0 failed (HEAD `e372acb`).
> **Tạo**: CP0, lần chạy Phase 8 startup.

---

## Mục tiêu Phase 8

Đưa Ant-Orchestrator từ MVP automated-test-verified sang trạng thái:

1. Production workflow với real provider và real worker.
2. Context Preparation thực sự được wired.
3. Business result và artifact rõ ràng.
4. CLI dành cho end user.
5. Native executable không yêu cầu người dùng cài Python.
6. Distribution qua NPM.
7. Real-provider release smoke test.

---

## Quyết định đã frozen (không thay đổi trong Phase 8)

| # | Quyết định |
|---|---|
| F1 | Python Core được giữ nguyên |
| F2 | Không viết lại Ant-Orchestrator bằng Node.js |
| F3 | NPM là distribution channel chính |
| F4 | End user không cần tự cài Python |
| F5 | Global và local npm installation đều được hỗ trợ |
| F6 | Không publish package thật trước Product Owner approval |
| F7 | `ant run` không được âm thầm sử dụng `DeterministicStubAdapter` |
| F8 | Deterministic execution chỉ dùng trong `self-test` hoặc verification mode rõ ràng |
| F9 | Live smoke test phải kiểm tra artifact thực, không chỉ status |
| F10 | Memory write không thuộc Phase 8 |
| F11 | README pre-existing change phải được bảo toàn suốt Phase 8 |
| F12 | Không đóng Phase 8 nếu chỉ có stub workflow |

---

## Các loại artifact — phân biệt rõ

| Loại | Mô tả |
|---|---|
| Source checkout | Python source trong repository |
| Python wheel | `.whl` build artifact từ `hatchling`/`setuptools` |
| Native executable | `onedir` bundle từ PyInstaller (spike CP2) |
| NPM launcher | `package.json` + Node launcher script trong root package |
| NPM platform package | `optionalDependencies` chứa native executable theo OS/arch |

---

## Pending Product Owner Decisions

Xem `PHASE_8_PO_DECISIONS.md` — tất cả quyết định dưới đây ở trạng thái `PENDING`.

| # | Quyết định | Provisional (chỉ dùng nội bộ) |
|---|---|---|
| PO-1 | Executable name | `<cli-command>` |
| PO-2 | NPM scope ownership | TBD |
| PO-3 | Package access: public/private | private (local Verdaccio) |
| PO-4 | License | `UNLICENSED` |
| PO-5 | Initial release version | `0.1.0-dev` |
| PO-6 | Package author/organization metadata | TBD |
| PO-7 | Repository/homepage metadata | TBD |
| PO-8 | Windows-only hay multi-platform trong Phase 8 | Windows x64 (provisional) |
| PO-9 | Python package publish hay chỉ build artifact | build artifact only (provisional) |
| PO-10 | Public package release thuộc Phase 8 hay chuẩn bị | chuẩn bị (provisional) |

---

## Checkpoint Dependency Graph

```
CP0 (Plan governance)
  └─► CP1 (ADR governance)
        └─► CP2 (Native spike — verdict trước khi tiếp tục packaging)
              └─► [PASS/CONDITIONAL PASS] CP3 (Production workflow wiring)
              └─► [FAIL/BLOCKED] → Evaluate Nuitka / Embedded Python → block CP7–CP10
CP3 (Production workflow wiring)
  └─► CP4 (Business result contract)
        └─► CP5 (CLI end-user surface)
              └─► CP6 (configure + doctor commands)
                    └─► CP7 (NPM launcher package)
                          └─► CP8 (NPM platform package — native executable)
                                └─► CP9 (Integration install test)
                                      └─► CP10 (Live provider smoke test)
```

**Blocker rule**: CP3 không được bắt đầu nếu CP2 chưa có verdict rõ ràng.

---

## CP0 — Normalize Audit & Plan Governance

### Entry criteria
- Phase 7 COMPLETED và HEAD đã xác nhận.
- Branch Phase 8 đã tạo từ đúng closure HEAD.
- README pre-existing diff đã ghi nhận checksum.

### Scope
- Tạo plan chính thức (file này).
- Tạo `PHASE_8_PO_DECISIONS.md`.
- Kiểm tra exit-code contract hiện tại (PF-8 audit).
- Không thay đổi source code.

### Exit criteria
- Plan tồn tại trong repository.
- Không còn circular dependency ở CP2 (probe độc lập, không import CLI chưa có).
- CP4 có Result contract scope.
- Recovery semantics đúng (PF-4).
- Configure có non-interactive requirement (PF-5).
- Worker routing contract tồn tại (PF-6).
- Artifact safety contract tồn tại (PF-7).
- Exit-code audit tồn tại (PF-8).
- Doctor live-cost boundary tồn tại (PF-9).
- Command placeholder `<cli-command>` được dùng đúng (PF-10).
- README không bị chỉnh sửa.
- Không có source behavior change.

### Commit boundary
```
docs(plan): finalize phase 8 implementation governance
```
Chỉ chứa plan và governance artifacts. Không stage README.

### Rollback rule
Nếu plan không đạt exit criteria: không commit, ghi blocker, báo cáo.

---

## CP1 — Governance & Provisional ADRs

### Entry criteria
- CP0 PASS và commit hợp lệ.

### Scope
- Tạo/cập nhật `ADR-0009-npm-distribution.md` (status: ACCEPTED cho frozen decisions).
- Tạo `ADR-0010-native-packaging.md` (status: PROPOSED — chưa spike).
- Không thay đổi source code.

### Exit criteria
- Frozen decisions và pending decisions được phân biệt rõ trong ADR.
- Không có metadata giả (npm scope, license, version chưa chốt → ghi PENDING).
- ADR-0010 vẫn `PROPOSED`.
- README không bị stage.

### Commit boundary
```
docs(adr): define phase 8 distribution governance
```

### Rollback rule
Nếu ADR có conflict với frozen decisions: không commit, sửa lại.

---

## CP2 — Native Packaging Feasibility Spike

### Entry criteria
- CP1 PASS và commit hợp lệ.

### Scope
- Tạo `scripts/spikes/native_probe.py` — probe độc lập.
- Tạo build spec nếu cần.
- Tạo `docs/plans/PHASE_8_SPIKE_NATIVE.md` — spike report.
- Cập nhật ADR-0010 với evidence sau spike.

#### PF-1 tuân thủ — không circular dependency
Probe không import CLI command chưa tồn tại. Probe là executable riêng, không phải `<cli-command> --version`.

Probe checks bắt buộc:
1. Python runtime info.
2. Platform/architecture.
3. Version-module prototype (nội bộ, không phải CLI).
4. SQLite import + CRUD tối thiểu trong temp dir.
5. JSON1 extension.
6. LangGraph import.
7. LangGraph checkpoint SQLite import.
8. LiteLLM import.
9. FastAPI import.
10. Uvicorn import.
11. CA certificate resolution.
12. SSL context creation.
13. Package data/resource loading.
14. Unicode arguments.
15. Current working directory.
16. Path có khoảng trắng.
17. stdout/stderr.
18. Non-zero exit code propagation.
19. Temp directory cleanup.

Không gọi provider. Không gửi network request. Không dùng API key.

### Clean environment requirement
- Chạy ngoài source checkout.
- Trong path có khoảng trắng.
- Python bị loại khỏi PATH trong process test.
- Không dùng editable install runtime.

### Defender requirement
- Windows Defender phải bật.
- Không disable, không add broad exclusion.
- Nếu quarantine/block → verdict `BLOCKED`.

### Spike verdict
Một trong: `PASS` / `CONDITIONAL PASS` / `FAIL` / `BLOCKED`.

#### Nếu PASS hoặc CONDITIONAL PASS
- Cập nhật ADR-0010 với evidence.
- Có thể chuyển `ACCEPTED` nếu không có architecture blocker.
- Phase tiếp tục CP3 sau Product Owner review.

#### Nếu FAIL
- Không bắt đầu CP3 packaging-dependent work.
- Không bắt đầu CP7–CP10.
- Tạo decision note đánh giá: Nuitka / Embedded Python / alternative.
- Báo blocker.

#### Nếu BLOCKED
- Không tuyên bố feasibility PASS.
- Ghi điều kiện cần để chạy lại.
- Dừng trước CP3 nếu blocker ảnh hưởng architecture.

### Exit criteria
- Probe source tồn tại và chạy được.
- Spike report đầy đủ với verdict rõ ràng.
- ADR-0010 cập nhật với evidence.
- Không có production binary trong Git.

### Commit boundary
```
spike(packaging): validate Windows native bundle feasibility
```

### Rollback rule
Nếu spike không có verdict rõ ràng: không commit, ghi trạng thái thực tế.

---

## CP3 — Production Workflow Wiring

> **Blocker**: Không bắt đầu nếu CP2 verdict chưa có hoặc là FAIL/BLOCKED với architecture impact.

### Entry criteria
- CP2 PASS hoặc CONDITIONAL PASS.
- Product Owner đã review spike và approve tiếp tục.

### Scope
- Wire real provider vào composition root.
- Wire Context Preparation thực sự (không stub).
- Đảm bảo `ant run` không dùng `DeterministicStubAdapter`.
- Deterministic mode chỉ khả dụng qua flag rõ ràng.

### PF-4 tuân thủ — Recovery semantics đúng

Live recovery scenario:
```
workflow đạt AWAITING_APPROVAL
→ process kết thúc/restart
→ status vẫn AWAITING_APPROVAL
→ approve task hoặc approval
→ workflow auto-resume từ checkpoint
→ không tạo duplicate WorkflowRun
→ không chạy lại completed ExecutionAttempt
```

`run` sau restart chỉ dùng để kiểm tra idempotency hoặc recovery ở RUNNING, không thay thế approval.

### PF-6 tuân thủ — Worker routing contract

Phải định nghĩa:
```
Task classification
→ WorkerKind (enum/constant)
→ Worker registry
→ Worker factory
→ Worker execution
```

Phải trả lời rõ:
- Khi nào chọn Documentation Ant.
- Khi nào chọn Test Ant.
- Unsupported task xử lý ra sao.
- Có fallback worker hay không.
- Queen quyết định worker hay routing deterministic.
- Worker provider/model có thể cấu hình riêng không.
- Context criteria khác nhau thế nào theo worker.
- Validation strategy khác nhau thế nào theo worker.

Không hardcode mọi task vào Documentation Ant.

### PF-7 tuân thủ — Artifact write safety contract

Ba loại output:

**Internal artifact**: `.ant/artifacts/...`

**Proposed project change** (staged): `.ant/handoff/...`

**Applied project change**: `<project source/docs/tests>`

Phải xác định:
- Worker chỉ tạo staged artifact, không ghi trực tiếp vào project.
- `SIGNIFICANT_WRITE` gate xảy ra trước apply.
- Reject có rollback.
- Atomic apply.
- Scope allowlist.
- Workspace-boundary enforcement.
- Path traversal prevention.
- Symlink handling.
- Artifact digest.
- File overwrite policy.
- Cleanup khi workflow fail.

Architecture ưu tiên:
```
Worker tạo staged artifact
→ validate
→ approval nếu cần
→ atomic apply
→ persist TaskResult
```

---

## CP4 — Business Result Contract

### Entry criteria
- CP3 PASS với real workflow chạy được.

### Business Result contract (tối thiểu)

```
TaskResult
├── task_id
├── workflow_run_id
├── status
├── summary
├── artifacts[]
│   ├── relative_path
│   ├── media_type
│   ├── digest
│   └── created_by_attempt_id
├── failure_reason
├── completed_at
└── result_version
```

### Phải xác định
- Result được tạo ở node nào.
- Result được persist ở đâu (SQLite, migration cần không).
- Artifact reference dùng relative path.
- Digest được tính và xác minh thế nào.
- Result terminal có immutable không.
- Retry/regroup ảnh hưởng result thế nào.
- Failed/rejected/cancelled result chứa thông tin gì.
- API và CLI lấy result qua service/port nào.

---

## CP5 — CLI End-User Surface

### Entry criteria
- CP4 PASS với result contract.

### Scope
- Implement `<cli-command>` với các subcommands cần thiết.
- `<cli-command> run` — chạy workflow real provider.
- `<cli-command> task result` — lấy TaskResult.
- Sử dụng command placeholder cho đến khi PO-1 được chốt.

### PF-8 tuân thủ — Exit-code matrix

Phải audit contract hiện tại trước khi thêm exit code mới:

| Nhóm lỗi | Exit code hiện tại | Exit code đề xuất | Backward-compatible |
|---|---|---|---|
| Success | 0 | 0 | Yes |
| General failure | 1 | 1 | Yes |
| Usage/input validation | TBD (audit) | TBD | TBD |
| Workspace | TBD (audit) | TBD | TBD |
| Persistence/bootstrap | TBD (audit) | TBD | TBD |
| Workflow state | TBD (audit) | TBD | TBD |
| Approval | TBD (audit) | TBD | TBD |
| Runtime configuration/provider | TBD (audit) | TBD | TBD |

Nếu thêm exit code mới: phải có enum/constants, test, CLI docs, backward compatibility note.

---

## CP6 — Configure & Doctor Commands

### Entry criteria
- CP5 PASS với CLI surface.

### PF-5 tuân thủ — Configure non-interactive mode

Phải có cả:
1. **Interactive mode**: wizard tương tác.
2. **Non-interactive/scriptable mode**: option flags tương ứng config schema thực tế.

Non-interactive requirements:
- Config validation.
- Atomic file write.
- Không ghi secret.
- Không làm hỏng YAML hợp lệ.
- Rollback nếu write thất bại.
- Machine-readable output nếu CLI convention hỗ trợ.

Integration test bắt buộc:
```
configure
→ process restart
→ composition dùng đúng provider/model
```

### PF-9 tuân thủ — Doctor live-cost boundary

**Default doctor** (`<cli-command> doctor`):
- Không gọi LLM.
- Không phát sinh chi phí.
- Chỉ kiểm tra: config, credential presence, filesystem, SQLite, local endpoint metadata.

**Live connectivity check** (`<cli-command> doctor --live`):
- Có thể kiểm tra network/auth/model availability.
- Không gửi completion request.
- Phải cảnh báo có thể phát sinh chi phí.
- Không bật mặc định.

**Model invocation** (`<cli-command> doctor --invoke-model`):
- Flag riêng biệt.
- Cảnh báo rõ ràng về chi phí.
- Không log prompt/output nhạy cảm.

---

## CP7 — NPM Launcher Package

### Entry criteria
- CP6 PASS với configure và doctor.
- CP2 PASS hoặc CONDITIONAL PASS.
- Executable name PO-1 đã được chốt.

### Scope
- Root launcher package với `package.json`.
- Node launcher script gọi native executable.
- Global và local install được hỗ trợ.
- Không fallback system Python.
- Không postinstall download.
- Không telemetry.

---

## CP8 — NPM Platform Package (Native Executable)

### Entry criteria
- CP7 PASS.
- Native executable từ CP2 spike được hardened.

### Scope
- `optionalDependencies` theo OS/arch.
- Platform package chứa native executable.
- Install smoke test.

---

## CP9 — Integration Install Test

### Entry criteria
- CP8 PASS.

### Scope
- Global npm install test trên Verdaccio local.
- Local npm install test.
- Không dùng npm credentials thật.
- Không publish public.

---

## CP10 — Live Provider Smoke Test

### Entry criteria
- CP9 PASS.
- Product Owner approval cho live provider test.

### Scope
- Real provider (không stub).
- Kiểm tra artifact thực, không chỉ status.
- Ghi evidence đầy đủ.

---

## Quality Gate

Trước mọi commit trong Phase 8:

```bash
ruff check src/
ruff format --check src/
python -m mypy src/ --strict
pytest tests/ -x --timeout=60
python -m scripts.quality.gate
git diff --check
```

File size gate: mỗi file tối đa 350 dòng.

Import boundary: file trong package phải import đúng layer.

---

## Secret Scan — mỗi commit

Không stage:
- `.env`
- API key
- npm token
- database runtime
- certificate private key
- provider response
- local absolute path không cần thiết
- build cache
- native binary

---

## Exit-Code Audit (PF-8)

Phải audit `src/` trước CP5 để điền đủ exit-code matrix. Xem CP5 section.

Placeholder `TBD (audit)` sẽ được điền khi audit hoàn tất tại CP5.

---

## Commit Chain Phase 8

```
CP0: docs(plan): finalize phase 8 implementation governance
CP1: docs(adr): define phase 8 distribution governance
CP2: spike(packaging): validate Windows native bundle feasibility
CP3: feat(phase8-cp3): wire production workflow with real provider
CP4: feat(phase8-cp4): implement business result contract
CP5: feat(phase8-cp5): add CLI end-user surface
CP6: feat(phase8-cp6): add configure and doctor commands
CP7: feat(phase8-cp7): add NPM launcher package
CP8: feat(phase8-cp8): add NPM platform package with native executable
CP9: test(phase8-cp9): integration install test
CP10: test(phase8-cp10): live provider smoke test
```

Không squash checkpoint. Không amend Phase 0–7.
