# ANT-ORCHESTRATOR MASTER ROADMAP

Phiên bản: v1.0
Ngôn ngữ: Tiếng Việt
Trạng thái tài liệu: Active — nguồn tham chiếu lâu dài

---

## 1. Mục đích tài liệu

Đây là **Master Roadmap duy nhất** của Ant-Orchestrator. Tài liệu mô tả các **phase và milestone
cấp cao** từ trạng thái hiện tại (chưa có source code) tới một MVP chứng minh được vòng lặp điều
phối AI có kiểm soát.

Roadmap **không** chứa task implementation chi tiết, không lặp lại nội dung Foundation, không ước
lượng thời gian bằng ngày/tuần. Task chi tiết của từng phase sẽ nằm trong file checkpoint/plan riêng
ở các nhiệm vụ sau.

Roadmap tham chiếu (không sao chép) các tài liệu frozen trong `docs/product/`: `FOUNDATION.md`,
`TECHNICAL_FOUNDATION.md`, `MVP_SCOPE.md`, `WORKFLOW_SPEC.md`, `AGENT_OPERATING_MODEL.md`,
`CONTEXT_POLICY.md`, `ENERGY_POLICY.md`, `ADAPTER_CONTRACT.md`, `PROJECT_STRUCTURE.md`,
`DECISION_LOG.md` và `adr/*`.

---

## 2. Nguyên tắc quản trị Roadmap

- Roadmap chỉ mô tả phase và milestone cấp cao; task chi tiết nằm ở checkpoint/plan riêng.
- Không sửa Foundation/Technical Foundation thông qua Roadmap. Mọi thay đổi nền tảng cần ADR riêng.
- Mọi thay đổi scope phải ghi vào **§14 Nhật ký thay đổi**.
- Một phase chỉ được đánh dấu `COMPLETED` khi đáp ứng Definition of Done **và có evidence** (code +
  test + tài liệu). Không đánh dấu hoàn thành chỉ dựa trên báo cáo của agent.
- Hạng mục phát sinh phải được phân loại: bắt buộc cho phase hiện tại / technical debt / phase sau /
  parking lot. Không âm thầm chèn scope.
- Trạng thái chuẩn dùng trong roadmap:

```text
NOT_STARTED
IN_PROGRESS
BLOCKED
REVIEW_REQUIRED
COMPLETED
DEFERRED
```

- Không đưa công nghệ chưa được chốt vào như một quyết định chính thức. Các lựa chọn còn mở được
  ghi ở **§13**.

---

## 3. Trạng thái hiện tại của dự án

Khảo sát repository (đối chiếu code với tài liệu):

| Hạng mục | Trạng thái |
|---|---|
| Tài liệu nền tảng (`docs/product/*`, `adr/*`, `docs/claude/*`) | Đã tồn tại và có bằng chứng |
| Rule/skill/checklist cho Claude (`.claude/*`) | Đã tồn tại và có bằng chứng |
| Source code (`src/ant_orchestrator/`) | Chưa tồn tại |
| `pyproject.toml`, cấu hình lint/type/test | Chưa tồn tại |
| `tests/` | Chưa tồn tại |
| Core domain, adapters, workflows, workers, context, memory, energy, CLI, API | Chỉ có trong tài liệu |
| `.ant/` workspace runtime | Chỉ có trong tài liệu (mô tả ở `PROJECT_STRUCTURE.md`) |

**Kết luận**: toàn bộ thành phần code ở trạng thái `NOT_STARTED`. Git branch `develop`, working tree
sạch. Bộ tài liệu frozen nhất quán, **không phát hiện mâu thuẫn nội bộ**.

---

## 4. Phạm vi MVP

MVP chứng minh **một vòng lặp điều phối AI có kiểm soát**, tiết kiệm context/energy hơn cách dùng
một agent lớn đọc toàn bộ project. MVP dùng **Autonomy Level 1** (Human giao task và phê duyệt
quyết định lớn; hệ thống tự retry/validation trong giới hạn).

Vòng lặp mục tiêu:

```text
Human gửi task → Queen phân tích → tạo kế hoạch có cấu trúc → phân rã micro-task
→ chọn worker phù hợp → cấp context tối thiểu → Worker thực thi trong boundary
→ chạy validation/test → retry/regroup/escalate có kiểm soát → Queen review
→ persist state + evidence → human approval ở decision gate → trả kết quả cho Human
```

Trong phạm vi MVP:

- CLI (Typer) tối thiểu để vận hành vòng lặp; FastAPI surface để quan sát.
- LangGraph workflow với checkpoint, approval pause/resume, retry/regroup/escalate.
- Adapter contract provider-neutral; **một** cloud Queen adapter thật + **một** Ollama adapter thật
  + mock/fake adapter cho test.
- Execution security boundary; Context Package + manifest; Energy enforcement.
- SQLite persistence + `.ant/` workspace.
- Hai worker frozen: **Documentation Ant** và **Test Ant**.
- Memory **tối thiểu, deterministic** (record + truy xuất có giới hạn).

---

## 5. Ngoài phạm vi MVP

Theo `MVP_SCOPE.md §5` và quyết định review, các hạng mục sau **không** thuộc MVP:

- Fully/Semi-Autonomous Colony, Roadmap Evolver, Performance Evaluator, Adaptive Energy Optimizer,
  Self-Evolving Colony.
- Advanced Colony Memory: semantic/embedding/vector retrieval, memory scoring tự học, expiration
  nâng cao, archival automation, memory consolidation, adaptive memory selection.
- Git **write** automation (commit/push/merge/checkout/reset/rebase/đổi history).
- Full sandbox cấp container; semantic context engine phức tạp.
- Multi-user platform, distributed worker cluster, production deployment automation, CI/CD
  deployment pipeline, fine-tuning/training model, marketplace/plugin, complex UI.
- Worker thứ 3+ (Frontend/Backend/DevOps/Security/...).

---

## 6. Kiến trúc mục tiêu ở mức tổng quan

Kiến trúc khái niệm (chi tiết ở `FOUNDATION.md §7` và `PROJECT_STRUCTURE.md`):

```text
Human / Vision Owner → Queen → Orchestrator Core → Adapter Layer → Specialized Ants → Tools/Codebase
```

Nguyên tắc kiến trúc xuyên suốt:

- **Core domain provider-neutral**: domain không phụ thuộc LiteLLM, LangGraph hay provider-specific
  type. LiteLLM (gateway) và LangGraph (workflow) là implementation detail ở tầng adapter/workflow.
- **Adapter-first**: mọi tích hợp model/tool đi qua adapter có usage normalization, timeout,
  structured error, capability metadata.
- **Context isolation**: worker chỉ nhận context tối thiểu; mọi package có manifest kiểm thử được.
- **Energy accounting + enforcement** ngay từ đầu.
- **Human approval** là capability nền tảng, hiện diện trong domain, workflow state, persistence,
  CLI/API và audit.

### Ba tầng tiến hóa

- **Tầng A — Bootstrap**: Claude CLI được PO dùng để **viết code** Ant-Orchestrator. Đây là công cụ
  phát triển, **không** phải runtime architecture của sản phẩm. Claude CLI (bootstrap) và runtime
  LLM adapter là hai vai trò độc lập.
- **Tầng B — MVP Runtime**: phạm vi Phase 0–7 + MVP Release Gate.
- **Tầng C — Long-term Evolution**: xem §10 (post-MVP). Không đưa vào MVP.

---

## 7. Sơ đồ phụ thuộc giữa các phase

```text
Phase 0  Scaffolding & Quality Tooling
   │
Phase 1  Core Domain, Config, Workspace & Minimal State Persistence
   │            (persistence tối thiểu PHẢI có trước workflow)
Phase 2  Adapter Contracts, Model Gateway & Test Doubles
   │
Phase 3  Execution Boundary (3A) + Context Package (3B) + Energy Enforcement (3C)
   │            (boundary PHẢI có trước worker thật)
Phase 4  LangGraph Walking Skeleton + Checkpoint + Human Approval   ── worker = STUB
   │            (CLI tối thiểu xuất hiện ở đây để vận hành skeleton)
Phase 5  Documentation Ant — First Real Vertical Slice              ── worker thật #1
   │
Phase 6  Test Ant + Retry/Regroup/Escalate + MVP Workflow Completion ── Full MVP Candidate
   │
Phase 7  Minimal Memory Retrieval + CLI/API Surface + MVP Hardening
   │
[MVP RELEASE GATE]
```

Ràng buộc phụ thuộc: không phase nào phụ thuộc phase phía sau. Memory record tối thiểu (P1) có trước
memory retrieval (P7). Worker thật (P5/P6) sau execution boundary (P3). Walking Skeleton (P4) không
phụ thuộc bất kỳ capability nào chỉ xuất hiện ở P7.

---

## 8. Master Phases

> Mỗi phase gồm: Mục tiêu · Phạm vi · Deliverables · Điều kiện bắt đầu · Definition of Done ·
> Phụ thuộc · Rủi ro chính · Những việc không làm. Kèm **Trạng thái**, **Evidence kỳ vọng**,
> **Decision gate** (nếu có). Tất cả phase hiện ở `NOT_STARTED`.

### Phase 0 — Project Scaffolding & Quality Tooling

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Dựng skeleton package và **quality gate local tự động** làm guardrail cho mọi phase sau.

#### Phạm vi
- Tạo `src/ant_orchestrator/` theo `PROJECT_STRUCTURE.md` (api, cli, core, workflows, adapters,
  workers, context, memory, energy, tools, config) + `tests/` + `pyproject.toml`.
- Bộ tooling tối giản: **Ruff lint + Ruff format + mypy + pytest** (không dùng Black — trùng vai trò).
- **Một lệnh thống nhất** chạy lint + format-check + type-check + test.
- Script kiểm tra **giới hạn ≤350 dòng/file** (COD-004) tự động.
- `ant --help` (Typer rỗng) chạy được.

#### Deliverables
Package skeleton cài được; cấu hình tooling; lệnh check thống nhất; script file-size.

#### Điều kiện bắt đầu
Repository hiện tại (chỉ có docs). Không có phụ thuộc kỹ thuật trước đó.

#### Definition of Done
`pip install -e .` thành công; lệnh check thống nhất xanh trên skeleton; script file-size chạy và
pass; CLI rỗng phản hồi `--help`.

#### Evidence kỳ vọng
Output lệnh check; kết quả script file-size; bản ghi cấu hình tooling.

#### Phụ thuộc
Không.

#### Rủi ro chính
Over-tooling (thêm dependency trùng vai trò); quality gate quá rộng gây false-positive.

#### Những việc không làm
CI/CD deployment pipeline (DEFERRED — §10); custom static analyzer phức tạp cho mọi literal; bất kỳ
logic nghiệp vụ nào.

---

### Phase 1 — Core Domain, Config, Workspace & Minimal State Persistence

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Domain thuần Python + **persistence tối thiểu** tồn tại **trước** mọi workflow, cho phép dừng /
persist / resume.

#### Phạm vi
- Domain model: Task + status enum (mở rộng `WORKFLOW_SPEC §15`), WorkerRun, EnergyUsage,
  Workflow **checkpoint**, **Approval state**, Execution evidence, Handoff record tối thiểu,
  Pheromone/event record tối thiểu.
- Trạng thái workflow phải bao gồm **approval** và **terminal** (xem §9 và Phase 4):
  `WAITING_FOR_APPROVAL`/`APPROVAL_REQUIRED`/`APPROVED`/`REJECTED` và `CANCELLED`/`FAILED`/
  `COMPLETED` (hoặc tên tương đương nếu `WORKFLOW_SPEC` đã định nghĩa khác).
- SQLite repository (pattern repository); `ant init` tạo `.ant/` đúng layout `PROJECT_STRUCTURE §4`;
  config loading (`.ant/config.yaml`).

#### Deliverables
Domain models; SQLite persistence; `.ant/` init; config layer.

#### Điều kiện bắt đầu
Phase 0 `COMPLETED`.

#### Definition of Done
CRUD Task + WorkerRun + EnergyUsage; lưu/đọc lại checkpoint và approval state; `.ant/` sinh đủ thư
mục; **domain không import LiteLLM/LangGraph/provider-specific type** (kiểm tra import boundary tự
động); unit test xanh.

#### Evidence kỳ vọng
Test report CRUD/checkpoint; bản ghi import-boundary; snapshot layout `.ant/`.

#### Phụ thuộc
Phase 0.

#### Rủi ro chính
Domain rò rỉ phụ thuộc framework/provider; schema state không đủ cho resume.

#### Những việc không làm
Memory retrieval nâng cao; LangGraph; gọi model thật; embedding/vector.

---

### Phase 2 — Adapter Contracts, Model Gateway & Test Doubles

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Ranh giới adapter **provider-neutral** + gateway thật tối thiểu, không xây mọi provider.

#### Phạm vi
- **Model adapters**: `LLMAdapter` interface (usage normalization, timeout, structured error,
  capability metadata) theo `ADAPTER_CONTRACT.md`; **một cloud Queen adapter thật chọn qua config**;
  **một Ollama adapter thật**; **mock/fake adapter cho test**. Claude/OpenAI/Gemini chỉ cần adapter
  boundary, chưa implement hết.
- **Execution/tool adapters** (định nghĩa contract; enforcement ở Phase 3): Filesystem, Shell,
  Test runner. **Git**: chỉ read state + tạo diff/change evidence (xem §13/§10 — không write).
- LiteLLM là implementation của gateway; domain/contract **không** lộ LiteLLM-specific type.
- Phân biệt rõ mức rủi ro: model invocation ≠ shell/filesystem execution.

#### Deliverables
Interface adapter; cloud + Ollama adapter thật; test doubles; tool adapter contracts.

#### Điều kiện bắt đầu
Phase 1 `COMPLETED`.

#### Definition of Done
Gọi 1 cloud + Ollama qua interface thống nhất, usage chuẩn hóa + log + timeout + structured error;
adapter mock được trong test; kiểm tra domain vẫn không phụ thuộc LiteLLM type.

#### Evidence kỳ vọng
Model usage record; tool invocation record (contract); test với mock adapter.

#### Phụ thuộc
Phase 1.

#### Decision gate
Chốt provider bootstrap cho cloud adapter đầu tiên **tại đầu phase này** theo availability/
capability/cost/testability (xem §13). Không frozen provider bằng roadmap.

#### Rủi ro chính
Provider lock-in trong domain; gộp nhầm model và execution adapter cùng mức rủi ro.

#### Những việc không làm
Implement đủ mọi provider; Git write; enforcement bảo mật (Phase 3).

---

### Phase 3 — Execution Boundary, Context Package & Energy Enforcement

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Ba cơ chế bảo vệ **kiểm thử được**, hoàn tất **trước** khi có worker thật. Phase gồm ba milestone
nội bộ.

#### Phạm vi
**3A — Execution Boundary**: workspace/path policy; command allowlist/policy; timeout; output limit;
secret protection (chặn `.env`/credential/private key vào context/log); audit evidence cho hành động
worker.

**3B — Context Package**: context selection; **manifest** (artifact chọn/loại, lý do, nguồn, size
ước tính, budget còn lại, redaction đã áp, task/worker nhận); scope enforcement; redaction;
token/size budget.

**3C — Energy Policy** (4 capability theo `ENERGY_POLICY.md`): measurement; budget reservation;
**enforcement**; routing (local-first; escalate cloud khi cần; tránh gọi model nếu dùng được
deterministic tool/cache/kết quả cũ); approval/escalation khi vượt budget.

#### Deliverables
Execution boundary enforcer; context package builder + manifest; energy manager đủ 4 capability.

#### Điều kiện bắt đầu
Phase 2 `COMPLETED`.

#### Definition of Done (automated test bắt buộc)
- Không tự động gửi toàn bộ repository; file ngoài allowed scope không xuất hiện; secret pattern bị
  loại/che; package không vượt budget.
- **Workflow bị từ chối / dừng / downgrade / chuyển chờ approval khi chạm energy policy** — không
  chỉ "ghi được log".
- Boundary chặn path/command ngoài phạm vi; output bị truncate đúng giới hạn.

#### Evidence kỳ vọng
Context manifest; execution record + audit log; energy enforcement test report.

#### Decision gate
Định nghĩa các gate vượt-budget chuyển sang chờ approval (liên kết Phase 4).

#### Phụ thuộc
Phase 2.

#### Rủi ro chính
Boundary có lỗ hổng path/secret; energy chỉ đo mà không enforce; context engine phình quá MVP.

#### Những việc không làm
Sandbox cấp container; Adaptive Energy Optimizer; semantic context engine; embedding/vector.

---

### Phase 4 — LangGraph Walking Skeleton, Checkpoint & Human Approval

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Bộ khung workflow chạy được với **worker stub**. Đây **không** phải MVP end-to-end.

#### Phạm vi
- Graph: plan → context → execute(**stub**) → validate → review → persist/handoff, + cạnh
  retry/regroup/escalate.
- State transition; **checkpoint**; **approval pause/resume**; adapter invocation; evidence
  collection.
- **Human Approval trong state machine**: workflow có thể dừng → persist checkpoint → chuyển trạng
  thái chờ duyệt → human approve/reject → resume từ checkpoint (không chạy lại toàn workflow) hoặc
  kết thúc có kiểm soát.
- **CLI tối thiểu** xuất hiện ở đây (init / task create / run / approve / cancel) để vận hành
  skeleton.

#### Deliverables
LangGraph skeleton; checkpoint + resume; approval flow; CLI tối thiểu.

#### Điều kiện bắt đầu
Phase 3 `COMPLETED`.

#### Definition of Done
Chạy 1 task tầm thường qua đủ node; chứng minh **dừng → persist → chờ approval → approve/reject →
resume từ checkpoint**; status transition persist; cancel đưa task về terminal an toàn (xem §9).

#### Evidence kỳ vọng
Checkpoint record; approval record; execution record; status transition log.

#### Decision gate (tối thiểu phải định nghĩa)
Trước ghi file phạm vi đáng kể; trước command ngoài nhóm an toàn mặc định; khi vượt energy budget;
khi retry gần/đạt giới hạn; khi Queen muốn thay đổi phạm vi task.

#### Phụ thuộc
Phase 3.

#### Rủi ro chính
Coi nhầm skeleton là MVP; approval/resume không bền vững qua restart.

#### Những việc không làm
Gọi đây là MVP end-to-end (execution còn stub); worker thật; memory retrieval.

---

### Phase 5 — Documentation Ant: First Real Vertical Slice

**Trạng thái**: `COMPLETED`

#### Mục tiêu
Thay stub bằng **worker thật đầu tiên** trong một scenario thực — **First Real Worker Slice**.

#### Phạm vi
- Documentation Ant chạy trong execution boundary (Phase 3), output contract đầy đủ
  (`AGENT_OPERATING_MODEL §12`). Validation: file tồn tại + section bắt buộc.
- **Khóa quyền Documentation Ant**: allowed path rõ ràng; **không** tự sửa Foundation, Technical
  Foundation, ADR frozen, `ROADMAP.md`, requirement/scope; document protected chỉ sửa khi có task +
  approval riêng; mọi thay đổi có diff + evidence; nội dung cập nhật dựa trên source code / test
  result / approved decision / task input; **không tự "chuẩn hóa"** làm thay đổi ý nghĩa quyết định
  frozen.
- First Real Vertical Slice dùng **tài liệu không protected** hoặc **fixture workspace an toàn**.

#### Deliverables
Documentation Ant thật; tích hợp vào graph; bộ permission có thể kiểm thử.

#### Điều kiện bắt đầu
Phase 4 `COMPLETED`.

#### Definition of Done
Scenario tạo/sửa tài liệu thật chạy end-to-end qua graph + approval + context manifest + energy
enforcement + boundary; evidence đầy đủ; test xác nhận worker **không** ghi ngoài allowed path và
**không** chạm document protected.

#### Evidence kỳ vọng
Output artifact/diff; context manifest; approval record; execution record.

#### Phụ thuộc
Phase 4.

#### Rủi ro chính
Worker vượt path/protected-doc; scope creep trong nội dung tài liệu.

#### Những việc không làm
Test Ant; retrieval nâng cao; sửa document protected.

---

### Phase 6 — Test Ant, Retry/Regroup/Escalate & MVP Workflow Completion

**Trạng thái**: `COMPLETED`

> Completion report: `docs/plans/PHASE_6_COMPLETION_REPORT.md` (initial `0818679`; corrected `656520e`; Docker `2d64333`).
> Closure corrections: `be2dbe5` (file-size + wheel archives) → `7a2711b` (offline fixture, no network at test time).
> Docker E2E: 7 PASSED real / 2 pre-existing SKIP — fixture image `sha256:12be62b2…` (pytest 9.1.1).
> Verdict: **PHASE 6 COMPLETED — FULL MVP CANDIDATE** — 1786 passed / 15 skipped / 0 failed.
> Commit chain: CP1 `6f4c171` → CP2 `280b2b5` → CP3 `fc91215` → CP4 `3d567b4` → CP5 `035b5fa`
> → CP6 `adf20eb` → CP6-correction `e744eba` → CP7 `f7a0967` → `be2dbe5` → `7a2711b`.

#### Mục tiêu
Hoàn tất vòng lặp MVP với cả hai worker frozen — **Full MVP Candidate**.

#### Phạm vi
- **Test Ant** (vai trò giới hạn): xác định test command được phép; chạy test trong execution
  boundary; thu output có giới hạn; phân loại failure; tạo **structured test report**; cung cấp
  evidence cho Queen; có thể đưa **diagnostic hint / failure analysis** để Queen quyết định bước
  tiếp theo. **Không** tự sửa implementation code, không commit, không sửa/xóa/skip test để làm
  pass, không mở rộng scope.
- **Retry / Regroup / Escalate** (định nghĩa tách bạch, có giới hạn + reason code + audit record +
  energy impact + terminal condition):
  - *Retry*: chạy lại cùng worker + cùng chiến lược khi failure tạm thời (model timeout, process
    interruption, transient adapter error).
  - *Regroup*: thay đổi context package / worker / model / tool / execution strategy — chỉ sau khi
    failure đã phân loại và còn budget.
  - *Escalate*: chuyển quyết định cho Queen / cloud model capability cao hơn / human approval.
  - Không implement thành vòng lặp gọi lại model không phân loại.
- Hoàn chỉnh MVP workflow loop với cả Documentation Ant và Test Ant.

#### Deliverables
Test Ant thật; cơ chế retry/regroup/escalate có phân loại; MVP workflow loop hoàn chỉnh.

#### Điều kiện bắt đầu
Phase 5 `COMPLETED`.

#### Definition of Done
Scenario có test fail → phân loại → retry/regroup trong giới hạn → escalate/review → handoff; cả 2
worker hoạt động theo contract; integration test xanh; retry không vượt giới hạn cấu hình.

#### Evidence kỳ vọng
Structured test report; retry/regroup record (reason code + energy impact); execution record; handoff.

#### Phụ thuộc
Phase 5.

#### Rủi ro chính
Test Ant vượt vai trò (sửa code/test); retry loop vô hạn không phân loại.

#### Những việc không làm
Worker thứ 3+; UI; Test Ant tự sửa business logic; Git write.

---

### Phase 7 — Minimal Memory Retrieval, CLI/API Surface & MVP Hardening

**Trạng thái**: `NOT_STARTED`

#### Mục tiêu
Bổ sung **memory retrieval tối thiểu deterministic** + surface quan sát + hardening, hoàn thiện MVP
candidate. (Memory record tối thiểu đã có từ Phase 1.)

#### Phạm vi
- **Memory retrieval tối thiểu, deterministic, kiểm thử được**: truy xuất theo colony/project, theo
  task, theo record type, theo tag/metadata rõ ràng; giới hạn số record trả về; **không dump toàn
  bộ memory** vào context.
- **CLI** hoàn chỉnh (logs / status / memory search) — bổ sung trên CLI tối thiểu của Phase 4.
- **FastAPI** surface (sau CLI): submit task; inspect task / worker run / logs.
- **Hardening**: observability, recovery, release validation.

#### Deliverables
Memory retrieval tối thiểu; CLI đầy đủ; FastAPI surface; bộ hardening.

#### Điều kiện bắt đầu
Phase 6 `COMPLETED`.

#### Definition of Done
Retrieval trả memory liên quan (theo bộ lọc xác định, có giới hạn) vào context package — không dump;
vòng lặp chạy được từ **CLI** và **API**; quan sát task/run/energy/approval; recovery sau restart.

#### Evidence kỳ vọng
Context manifest có memory đưa vào; execution/observability record; release validation report.

#### Phụ thuộc
Phase 6.

#### Rủi ro chính
Memory retrieval phình sang semantic/vector ngoài MVP; FastAPI mở scope quá sớm.

#### Những việc không làm
Semantic/embedding/vector retrieval; memory scoring tự học; expiration nâng cao; archival
automation; consolidation; adaptive selection; Roadmap Evolver/Performance Evaluator/Adaptive
Optimizer/Self-Evolving (Tầng C).

---

## 9. MVP Release Gate

MVP chỉ được coi là đạt khi demo scenario `MVP_SCOPE §8` chạy trọn vẹn **và** thỏa 6 chiều sau, mỗi
chiều có evidence:

**Correctness**: state transition hợp lệ; resume từ checkpoint; retry không vượt giới hạn; output
contract được validate.

**Control**: có approval gate; có cancel/stop với **terminal state** rõ ràng (`CANCELLED`/`FAILED`/
`COMPLETED`/`REJECTED` hoặc tên tương đương) — human có thể cancel task đang chờ hoặc ở safe
checkpoint; cancel không để workflow tiếp tục spawn worker; budget reservation chưa dùng được giải
phóng/ghi nhận; task terminal không tự resume; failure terminal có reason + evidence; có timeout;
có energy enforcement; không spawn worker vô hạn.

**Context & Security**: context manifest có evidence; không gửi full repo; secret redaction hoạt
động; filesystem + command boundary hoạt động.

**Observability**: truy vết được task / plan / worker run / model call / tool call / approval /
retry / energy / output evidence.

**Recovery**: process restart không mất task state; workflow resume từ checkpoint phù hợp; failure
được phân loại; không retry loop vô hạn.

**Quality**: unit + integration test xanh; ≥1 end-to-end scenario deterministic/reproducible; không
vi phạm giới hạn ≤350 dòng; không commit secret/generated artifact ngoài ý muốn.

Mỗi phase chỉ `COMPLETED` khi có evidence (code + test + tài liệu), không dựa trên báo cáo agent.

---

## 10. Các phase sau MVP (Tầng C & mở rộng)

Chỉ kích hoạt sau khi MVP đạt Release Gate và ổn định:

- **Autonomy nâng dần**: Semi-Autonomous → Autonomous → Self-Evolving Colony.
- **Queen capability**: Roadmap Evolver, Performance Evaluator, Adaptive Energy Optimizer.
- **Memory nâng cao**: semantic/embedding/vector retrieval, scoring tự học, lifecycle/expiration/
  archival automation, consolidation, adaptive selection.
- **Git write automation** (commit/push/merge/branch...) có kiểm soát.
- **Hạ tầng**: Postgres khi cần multi-user/remote; CI/CD **deployment** pipeline; complex UI;
  multi-user platform; distributed worker; marketplace/plugin.
- **Worker mở rộng**: Frontend/Backend/DevOps/Security/Research/... mỗi worker có mission, input/
  output contract, permission boundary, energy budget, evaluation metric.

(Lưu ý: **local automated quality gate** là bắt buộc từ Phase 0 và **không** thuộc nhóm DEFERRED;
chỉ CI/CD **deployment** pipeline mới DEFERRED.)

---

## 11. Rủi ro xuyên suốt

- **Context explosion**: nếu Context Package/manifest không enforce, token bùng nổ — rủi ro lõi của
  cả dự án.
- **Provider lock-in**: domain lỡ phụ thuộc LiteLLM/LangGraph/provider type → khó thay engine.
- **Worker vượt quyền**: thiếu execution boundary trước worker thật → ghi ngoài scope, lộ secret.
- **Energy chỉ đo không enforce**: workflow chạy vô hạn, vượt budget.
- **Approval/recovery không bền**: restart mất state, không resume được từ checkpoint.
- **Scope creep**: kéo Tầng C (self-evolving, semantic memory, Git write) vào MVP vì hấp dẫn kỹ thuật.
- **Retry không phân loại**: vòng lặp gọi lại model không có terminal condition.

---

## 12. Quy tắc thay đổi Roadmap

- Roadmap chỉ mô tả phase/milestone cấp cao; chi tiết nằm ở checkpoint/plan riêng.
- Không sửa Foundation/Technical Foundation qua Roadmap; thay đổi nền tảng cần ADR.
- Mọi thay đổi scope ghi vào **§14**.
- Phase chỉ `COMPLETED` khi đạt DoD + có evidence.
- Hạng mục phát sinh phân loại: bắt buộc phase hiện tại / technical debt / phase sau / parking lot.
- Không âm thầm chèn scope; không đưa công nghệ chưa chốt thành quyết định chính thức.

---

## 13. Các điểm cần Product Owner xác nhận

Khảo sát **không phát hiện mâu thuẫn** giữa các tài liệu frozen. Các điểm dưới đây **không chặn**
roadmap, chỉ cần PO xác nhận tại thời điểm phù hợp:

1. **Cloud provider bootstrap (chốt tại đầu Phase 2)**: core domain provider-neutral; provider chọn
   qua **configuration**; MVP chỉ cần **một** cloud provider thật hoạt động; provider cụ thể lựa
   chọn theo availability/capability/cost/testability. Claude, OpenAI và Gemini là adapter
   candidate; **không** provider nào được frozen bởi roadmap. (Claude CLI dùng để bootstrap project
   là vai trò độc lập, không quyết định runtime provider.)
2. **Phạm vi Git trong MVP**: mặc định MVP chỉ **đọc** repo state + tạo diff/change evidence, không
   write (commit/push/merge/checkout/reset/rebase/history). Xác nhận giữ mặc định này hay điều chỉnh.
3. **Cách thức "lệnh check thống nhất"** (Phase 0): để nhóm phát triển chọn (script/Make/nox/hatch)
   — chỉ là chi tiết vận hành, không ảnh hưởng kiến trúc.

---

## 14. Nhật ký thay đổi Roadmap

| Phiên bản | Thay đổi | Ghi chú |
|---|---|---|
| v1.0 | Khởi tạo Master Roadmap sau khảo sát repository (chưa có source code). 8 phase (0–7), MVP Release Gate 6 chiều, ba tầng tiến hóa. Áp dụng các điều chỉnh review: persistence hai cấp, human approval nền tảng, execution boundary trước worker thật, energy enforcement, context manifest, phân biệt Walking Skeleton/First Real Slice/Full MVP Candidate, tooling Ruff+mypy+pytest, memory MVP tối thiểu deterministic, Phase 3 chia 3A/3B/3C, khóa quyền Documentation Ant, giới hạn vai trò Test Ant, phân biệt Retry/Regroup/Escalate, runtime provider-neutral, Git write ngoài MVP, constants gate hợp lý, cancel/terminal state, evidence dạng artifact có cấu trúc. | Mọi phase `NOT_STARTED`. |
| v1.1 | Phase 0 chuyển `NOT_STARTED` → `COMPLETED` sau independent closure audit. Evidence: `python -m pip install -e ".[dev]"`, `ant --help`, `ruff check`, `ruff format --check`, `mypy src scripts`, `pytest` (19 passed), `python -m scripts.quality.file_size`, unified gate `python -m scripts.quality.gate` (5/5 PASS) — tất cả exit 0. Chi tiết: `docs/plans/PHASE_0_COMPLETION_REPORT.md`. Không sửa mục tiêu/scope/DoD Phase 0. | Phase 1–7 giữ `NOT_STARTED`. |
| v1.2 | Phase 1 chuyển `NOT_STARTED` → `COMPLETED` sau implementation theo `docs/plans/PHASE_1_PLAN.md` (8 checkpoint) + closure audit. Evidence: `python -m scripts.quality.gate` (5/5 PASS), `pytest` 127 passed, smoke test `ant init/status/config show`, AST import-boundary, dependency mới duy nhất `pyyaml`. Chi tiết: `docs/plans/PHASE_1_COMPLETION_REPORT.md`. Không sửa mục tiêu/scope/DoD Phase 1. | Phase 2–7 giữ `NOT_STARTED`. |
| v1.3 | Phase 3 chuyển `NOT_STARTED` → `COMPLETED` sau implementation 20 commits (CP0–CP9) + independent closure audit. Evidence: `python -m scripts.quality.gate` (5/5 PASS), `pytest` 974 passed 7 skipped, 22 import-boundary tests PASS, 14 integration tests (8 cases) PASS, R-CP3-2 CLOSED, R-CP3-1 ACCEPTED_MVP_LIMITATION. Branch: `phase/3-execution-boundary`. Chi tiết: `docs/plans/PHASE_3_COMPLETION_REPORT.md`. Không sửa mục tiêu/scope/DoD Phase 3. | Phase 4–7 giữ `NOT_STARTED`. |
| v1.4 | Phase 4 chuyển `NOT_STARTED` → `COMPLETED` sau implementation CP1–CP8 (10 commits, worker = stub) + independent closure audit CP9. Evidence: `python -m scripts.quality.gate` (5/5 PASS), `pytest` 1219 passed 7 skipped, mypy strict 151 files, `pip check` clean, restart E2E đa-process thật A–H (0 CP8 skip), CLI smoke `ant init/task create/run/status`. Branch: `develop` (không source branch riêng). Chi tiết: `docs/plans/PHASE_4_COMPLETION_REPORT.md`. Không sửa mục tiêu/scope/DoD Phase 4. | Phase 5–7 giữ `NOT_STARTED`. |
