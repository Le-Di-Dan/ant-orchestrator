# ANT-ORCHESTRATOR TECHNICAL FOUNDATION

Phiên bản: v0.1  
Trạng thái: Frozen Draft  
Ngôn ngữ: Tiếng Việt

---

# 1. Mục tiêu kỹ thuật

Technical Foundation này đóng băng các quyết định kỹ thuật nền tảng cho Ant-Orchestrator giai đoạn MVP.

Mục tiêu là giúp dự án có hướng triển khai rõ ràng, không bị đổi stack liên tục và không sa đà vào việc xây quá nhiều thứ trước khi chứng minh được vòng lặp MVP.

---

# 2. Nguyên tắc kỹ thuật cốt lõi

Ant-Orchestrator phải ưu tiên:

1. Đơn giản trước.
2. Điều phối trước, tự trị sau.
3. Local-first cho worker nhỏ.
4. Cloud model cho reasoning cấp cao.
5. Adapter-first để không phụ thuộc một provider.
6. Context isolation để chống context explosion.
7. Energy accounting ngay từ đầu.
8. Human approval cho quyết định rủi ro trong MVP.

---

# 3. Quyết định stack

## 3.1 Python-first core

Core của Ant-Orchestrator dùng Python.

Lý do:

- Hệ sinh thái AI/agent/tooling mạnh.
- Dễ tích hợp LangGraph, LiteLLM, Ollama, CLI tools.
- Dễ viết orchestration logic, queue, state machine.
- Phù hợp để phát triển daemon/API/CLI.

---

## 3.2 FastAPI daemon/API

Ant-Orchestrator sẽ có daemon/API dựa trên FastAPI.

Vai trò:

- Nhận task từ CLI/UI.
- Quản lý execution session.
- Cung cấp API để quan sát task, logs, memory, worker status.
- Là nền tảng cho UI tương lai.

---

## 3.3 Typer CLI

CLI dùng Typer.

Vai trò:

- Tạo colony/nest.
- Submit task.
- Inspect task.
- Xem logs.
- Chạy worker/test/review.
- Dùng được trước khi có UI.

Ví dụ lệnh tương lai:

```bash
ant init
ant task create "Fix failing auth tests"
ant task status <task_id>
ant task logs <task_id>
ant memory search "auth"
ant run
```

---

## 3.4 LangGraph-first workflow/state machine

Workflow orchestration ưu tiên LangGraph.

Lý do:

- Phù hợp để biểu diễn state machine.
- Hỗ trợ graph-based workflow.
- Dễ quản lý các node như plan, split, execute, test, review, retry.
- Phù hợp hơn chain tuyến tính đơn giản.

LangChain/CrewAI không bị cấm, nhưng không phải nền tảng chính trong MVP.

---

## 3.5 LiteLLM as LLM Gateway

LiteLLM dùng làm gateway thống nhất cho cloud/local model nếu phù hợp.

Vai trò:

- Gọi OpenAI.
- Gọi Claude.
- Gọi Gemini.
- Gọi Ollama/local model.
- Chuẩn hóa logging, token usage, model selection.

Ant-Orchestrator không gọi trực tiếp provider rải rác ở nhiều nơi.

---

## 3.6 Ollama local worker-first

Worker mặc định trong MVP ưu tiên local model qua Ollama khi task đủ nhỏ.

Ví dụ model ban đầu:

- Qwen Coder
- DeepSeek Coder
- Các model coding local khác nếu phần cứng cho phép

Local worker không thay thế cloud reasoning.

Local worker dùng cho việc có context hẹp và chi phí thấp.

---

## 3.7 SQLite initial local state

MVP dùng SQLite để lưu state local.

Lý do:

- Đơn giản.
- Không cần vận hành Postgres ngay.
- Phù hợp personal infrastructure.
- Dễ backup theo workspace.

Có thể nâng cấp Postgres khi cần multi-user, remote daemon hoặc production deployment.

---

## 3.8 `.ant/` workspace per project

Mỗi project có một thư mục `.ant/` riêng.

Vai trò:

- Lưu local state.
- Lưu task.
- Lưu memory.
- Lưu logs.
- Lưu cache.
- Lưu snapshots.
- Lưu config.

Ant-Orchestrator không nên phụ thuộc hoàn toàn vào global state.

---

# 4. Vai trò model

## 4.1 Queen dùng cloud model mặc định

Queen cần reasoning mạnh, hiểu context tổng, lập kế hoạch và review.

Trong MVP, Queen nên dùng cloud model theo mặc định.

Có thể là:

- Claude
- OpenAI
- Gemini

Tùy budget, quota, task type và chất lượng cần thiết.

---

## 4.2 Worker dùng local model trước

Worker nên dùng Ollama/local model trước nếu task đủ nhỏ.

Ví dụ:

- Viết test đơn giản.
- Sửa lỗi isolated.
- Update markdown.
- Tìm file liên quan.
- Tóm tắt log.

Nếu local worker fail hoặc task quá khó, Queen có thể escalate lên cloud model.

---

# 5. Autonomy Level MVP

MVP dùng Autonomy Level 1.

Nghĩa là:

- Human tạo task.
- Queen lập plan.
- Queen đề xuất chia task.
- Worker thực hiện task nhỏ.
- Test chạy tự động.
- Review có thể dùng cloud.
- Human vẫn xác nhận các thay đổi quan trọng.

Không tự merge code nguy hiểm.

Không tự deploy production.

Không tự chạy lệnh phá hủy.

---

# 6. Worker đầu tiên

MVP bắt đầu với 2 worker chính:

## 6.1 Documentation Ant

Vai trò:

- Tạo tài liệu.
- Update markdown.
- Tóm tắt kết quả.
- Ghi decision log.
- Ghi handoff.

## 6.2 Test Ant

Vai trò:

- Chạy test.
- Đọc lỗi test.
- Đề xuất fix.
- Viết test nhỏ.
- Xác minh regression.

Các worker khác sẽ bổ sung sau khi vòng lặp MVP ổn định.

---

# 7. Claude CLI

Claude CLI có thể được dùng như developer/bootstrap assistant.

Nhưng Ant-Orchestrator không phụ thuộc cứng vào Claude CLI.

Mọi tích hợp với Claude CLI phải đi qua adapter hoặc command runner có kiểm soát.

---

# 8. Những thứ chưa làm trong MVP

MVP không làm:

- Multi-user platform.
- Distributed worker cluster.
- Fine-tuning model.
- Full autonomous development.
- Production deployment automation.
- Complex UI.
- Long-term self-learning phức tạp.
- Marketplace worker.
- Plugin ecosystem.

---

# 9. Tiêu chí thành công kỹ thuật của MVP

MVP thành công nếu có thể chứng minh vòng lặp:

```text
Human tạo task
↓
Queen hiểu task
↓
Queen chia micro-task
↓
Worker local thực hiện một phần
↓
Test Ant chạy test
↓
Nếu fail thì retry có kiểm soát
↓
Queen review
↓
Ghi memory/log/handoff
```

với mức context/token thấp hơn cách gọi một coding agent lớn đọc toàn bộ project.
