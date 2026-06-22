# ANT-ORCHESTRATOR DOCUMENTATION INDEX

Phiên bản: v0.1  
Ngôn ngữ: Tiếng Việt  
Trạng thái: Draft để review

Bộ tài liệu này được tạo để bổ sung cho `FOUNDATION.md` và `TECHNICAL_FOUNDATION.md` của Ant-Orchestrator.

Mục tiêu của bộ tài liệu là giúp con người, Queen và các Worker Ant làm việc nhất quán, không bị trôi vision, không lãng phí context/token, và có thể phát triển dự án theo hướng có kiểm soát.

---

## 1. Tài liệu nền tảng

- `FOUNDATION.md`  
  Định nghĩa Ant-Orchestrator là gì, vision, triết lý đàn kiến, pain point, định hướng MVP.

- `TECHNICAL_FOUNDATION.md`  
  Đóng băng các quyết định kỹ thuật nền tảng: Python-first, FastAPI, Typer CLI, LangGraph, LiteLLM, Ollama, SQLite, `.ant/` workspace, autonomy level, worker ban đầu.

---

## 2. Tài liệu vận hành bắt buộc

- `PROJECT_STRUCTURE.md`  
  Quy định cấu trúc repo, workspace `.ant/`, nơi lưu state, memory, task, logs, adapter, worker.

- `AGENT_OPERATING_MODEL.md`  
  Mô tả Queen, Worker Ant, Scout, Documentation Ant, Test Ant; quyền hạn và giới hạn của từng loại agent.

- `CONTEXT_POLICY.md`  
  Quy định context isolation, cấp context tối thiểu, chống context explosion.

- `ENERGY_POLICY.md`  
  Quy định cách quản lý token, quota, GPU/RAM, thời gian và human attention.

- `WORKFLOW_SPEC.md`  
  Mô tả vòng đời task từ lúc nhận yêu cầu đến khi hoàn thành và ghi memory.

- `MEMORY_AND_PHEROMONE_SPEC.md`  
  Quy định Colony Memory, Pheromone, log, summary, decision trace.

- `MVP_SCOPE.md`  
  Đóng băng phạm vi MVP và những thứ chưa làm trong MVP.

- `ADAPTER_CONTRACT.md`  
  Chuẩn interface cho Claude/OpenAI/Gemini/Ollama adapter.

- `DECISION_LOG.md`  
  Danh sách quyết định đã chốt và nguyên tắc khi bổ sung quyết định mới.

---

## 3. ADR

Thư mục `adr/` dùng để lưu Architecture Decision Record.

Hiện có:

- `adr/ADR-0001-python-first-core.md`
- `adr/ADR-0002-langgraph-first.md`
- `adr/ADR-0003-litellm-gateway.md`
- `adr/ADR-0004-ollama-local-worker-first.md`
- `adr/ADR-0005-sqlite-initial-state.md`

---

## 4. Thứ tự đọc đề xuất

1. `FOUNDATION.md`
2. `TECHNICAL_FOUNDATION.md`
3. `MVP_SCOPE.md`
4. `AGENT_OPERATING_MODEL.md`
5. `WORKFLOW_SPEC.md`
6. `CONTEXT_POLICY.md`
7. `ENERGY_POLICY.md`
8. `MEMORY_AND_PHEROMONE_SPEC.md`
9. `PROJECT_STRUCTURE.md`
10. `ADAPTER_CONTRACT.md`
11. `DECISION_LOG.md`
12. `adr/*`

