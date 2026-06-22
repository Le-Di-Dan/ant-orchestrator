# PROJECT_STRUCTURE.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Tài liệu này quy định cấu trúc repo và workspace cho Ant-Orchestrator.

Mục tiêu là giúp con người, Queen và Worker Ant biết rõ:

- File nào nằm ở đâu.
- State được lưu ở đâu.
- Memory được lưu ở đâu.
- Logs được lưu ở đâu.
- Adapter và worker được tổ chức thế nào.

---

# 2. Cấu trúc repo đề xuất

```text
ant-orchestrator/
├── README.md
├── pyproject.toml
├── src/
│   └── ant_orchestrator/
│       ├── api/
│       ├── cli/
│       ├── core/
│       ├── workflows/
│       ├── adapters/
│       ├── workers/
│       ├── context/
│       ├── memory/
│       ├── energy/
│       ├── tools/
│       └── config/
├── tests/
├── docs/
│   ├── FOUNDATION.md
│   ├── TECHNICAL_FOUNDATION.md
│   ├── PROJECT_STRUCTURE.md
│   ├── AGENT_OPERATING_MODEL.md
│   ├── CONTEXT_POLICY.md
│   ├── ENERGY_POLICY.md
│   ├── WORKFLOW_SPEC.md
│   ├── MEMORY_AND_PHEROMONE_SPEC.md
│   ├── MVP_SCOPE.md
│   ├── ADAPTER_CONTRACT.md
│   ├── DECISION_LOG.md
│   └── adr/
└── examples/
```

---

# 3. Cấu trúc package

## `api/`

FastAPI daemon/API.

Chứa:

- HTTP routes.
- Request/response schema.
- Task submission endpoint.
- Logs endpoint.
- Memory inspection endpoint.

## `cli/`

Typer CLI.

Chứa:

- `ant init`
- `ant task create`
- `ant task status`
- `ant task logs`
- `ant memory search`
- `ant run`

## `core/`

Lõi điều phối.

Chứa:

- Task model.
- Worker registry.
- Scheduler.
- Permission guard.
- Execution session.
- Error handling.

## `workflows/`

LangGraph workflows.

Ví dụ:

- `task_execution_graph.py`
- `review_graph.py`
- `documentation_graph.py`

## `adapters/`

Adapter cho model/tool bên ngoài.

Ví dụ:

- `openai_adapter.py`
- `claude_adapter.py`
- `gemini_adapter.py`
- `ollama_adapter.py`
- `claude_cli_adapter.py`

## `workers/`

Các Specialized Ant.

Ví dụ:

- `documentation_ant.py`
- `test_ant.py`
- `frontend_ant.py`
- `backend_ant.py`

Trong MVP chỉ cần Documentation Ant và Test Ant.

## `context/`

Context Router và context packaging.

Chứa:

- File selection.
- Context budget.
- Context compression.
- Relevance scoring.

## `memory/`

Colony Memory và Pheromone.

Chứa:

- Memory writer.
- Memory reader.
- Summary store.
- Decision trace.

## `energy/`

Energy Manager.

Chứa:

- Token tracking.
- Model cost policy.
- Retry budget.
- Local/cloud routing.

## `tools/`

Wrapper cho tool thực thi.

Ví dụ:

- Shell runner.
- Git runner.
- Test runner.
- File patcher.

## `config/`

Cấu hình hệ thống.

Ví dụ:

- Model config.
- Provider config.
- Budget config.
- Safety config.

---

# 4. `.ant/` workspace per project

Mỗi project được Ant-Orchestrator quản lý sẽ có thư mục `.ant/` riêng.

Ví dụ:

```text
my-project/
├── src/
├── tests/
├── docs/
└── .ant/
    ├── config.yaml
    ├── state.sqlite
    ├── tasks/
    ├── memory/
    ├── pheromones/
    ├── logs/
    ├── cache/
    ├── snapshots/
    └── handoff/
```

---

# 5. Vai trò từng thư mục trong `.ant/`

## `config.yaml`

Cấu hình riêng của project.

Ví dụ:

- Project name.
- Default model.
- Local model.
- Test command.
- Lint command.
- Forbidden paths.
- Energy budget.

## `state.sqlite`

Local database cho project.

Lưu:

- Task state.
- Worker run.
- Model call summary.
- Energy usage.
- Retry count.
- Decision trace.

## `tasks/`

Lưu task file dạng markdown/yaml/json.

Ví dụ:

```text
tasks/
├── TASK-0001.md
├── TASK-0002.md
└── TASK-0003.md
```

## `memory/`

Lưu memory dài hạn của colony.

Ví dụ:

- Project facts.
- Architecture summary.
- Coding conventions.
- Known issues.
- Important decisions.

## `pheromones/`

Lưu dấu vết ngắn hạn/trung hạn từ worker.

Ví dụ:

- File liên quan.
- Test failure summary.
- Module risk.
- Work-in-progress notes.

## `logs/`

Lưu execution logs.

Không dùng logs như memory dài hạn.

## `cache/`

Lưu cache context, model response summary, search results.

Cache có thể xóa.

## `snapshots/`

Lưu snapshot trước/sau task nếu cần.

## `handoff/`

Lưu báo cáo bàn giao sau mỗi task/session.

---

# 6. Quy tắc đặt tên task

Task nên có ID ổn định:

```text
TASK-0001
TASK-0002
TASK-0003
```

Subtask:

```text
TASK-0001.1
TASK-0001.2
```

Worker run:

```text
RUN-TASK-0001-DOC-001
RUN-TASK-0001-TEST-001
```

---

# 7. Quy tắc không gian làm việc

Worker không được tự ý ghi vào `.ant/memory/` nếu không qua Memory Writer.

Worker không được sửa `FOUNDATION.md` hoặc `TECHNICAL_FOUNDATION.md` nếu không có human approval.

Worker không được xóa `.ant/state.sqlite`, `.git/`, source code chính hoặc file cấu hình quan trọng.

---

# 8. Nguyên tắc mở rộng

Cấu trúc repo có thể mở rộng, nhưng mọi thay đổi lớn phải có ADR.

Không thêm framework chỉ vì tiện ngắn hạn.

Không tạo nhiều layer abstraction nếu MVP chưa cần.
