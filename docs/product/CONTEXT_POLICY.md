# CONTEXT_POLICY.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Context Policy là một trong những tài liệu quan trọng nhất của Ant-Orchestrator.

Mục tiêu của tài liệu này là ngăn context explosion.

Triết lý chính:

> Một con kiến không được biết toàn bộ tổ kiến.

Worker Ant chỉ nhận context tối thiểu cần thiết để hoàn thành nhiệm vụ.

---

# 2. Vấn đề cần giải quyết

AI coding agent hiện nay thường tiêu tốn token vì:

- Đọc quá nhiều file.
- Sub-agent copy toàn bộ context.
- Mỗi retry lại gửi lại context dài.
- Logs dài bị đưa nguyên văn vào prompt.
- Tài liệu foundation bị load cả file dù chỉ cần một đoạn.
- Worker không biết file nào thực sự liên quan.

Ant-Orchestrator phải kiểm soát context như một tài nguyên khan hiếm.

---

# 3. Nguyên tắc context tối thiểu

Mỗi worker chỉ được nhận:

1. Task statement.
2. Acceptance criteria.
3. File liên quan.
4. Snippet liên quan.
5. Constraints.
6. Relevant memory.
7. Output format.

Không gửi toàn bộ codebase nếu không cần.

Không gửi toàn bộ lịch sử chat nếu không cần.

Không gửi toàn bộ log nếu chỉ cần failure summary.

---

# 4. Context Layers

Context được chia thành nhiều tầng.

## Layer 0 — System Rules

Các rule bất biến cho worker.

Ví dụ:

- Không mở rộng scope.
- Không sửa file ngoài quyền.
- Luôn báo files changed.
- Không xóa test để làm pass.

## Layer 1 — Foundation Summary

Không gửi toàn bộ Foundation mặc định.

Chỉ gửi summary ngắn nếu task cần biết vision.

## Layer 2 — Technical Constraints

Gửi các constraint kỹ thuật liên quan.

Ví dụ:

- Python-first.
- FastAPI.
- LangGraph.
- LiteLLM.
- Ollama local worker.

## Layer 3 — Task Context

Thông tin chính của task.

Đây là phần bắt buộc.

## Layer 4 — Relevant Files

Chỉ các file liên quan trực tiếp.

## Layer 5 — Retrieved Memory

Memory được truy xuất theo task.

Không dump toàn bộ memory.

## Layer 6 — Execution Evidence

Logs, test results, command output.

Phải được tóm tắt trước khi đưa vào model nếu dài.

---

# 5. Context Budget

Mỗi task cần có budget.

Ví dụ:

```yaml
context_budget:
  max_input_tokens: 12000
  max_files: 8
  max_file_tokens: 3000
  max_log_tokens: 2000
  allow_full_file: false
```

Worker local nên có budget nhỏ hơn cloud Queen.

---

# 6. File Selection Policy

Context Router phải chọn file theo thứ tự ưu tiên:

1. File được human chỉ định.
2. File được task mention trực tiếp.
3. File liên quan theo import/dependency.
4. File liên quan theo search keyword.
5. File được memory đánh dấu là liên quan.
6. File test tương ứng.

Không chọn file chỉ vì nằm gần thư mục.

---

# 7. Full File Policy

Không gửi full file nếu file dài và chỉ cần snippet.

Chỉ gửi full file khi:

- File nhỏ.
- Worker cần sửa cấu trúc toàn file.
- Task là refactor file đó.
- Test file cần đọc toàn bộ để hiểu expectation.

---

# 8. Log Policy

Không đưa log dài nguyên văn vào prompt.

Log phải được xử lý theo thứ tự:

1. Extract error lines.
2. Extract stack trace liên quan.
3. Extract command.
4. Extract environment nếu cần.
5. Summarize.

Worker chỉ nhận raw log nếu log ngắn.

---

# 9. Retry Context Policy

Mỗi retry không được copy toàn bộ context cũ.

Retry context phải gồm:

- Task summary.
- Attempt summary.
- What failed.
- Evidence.
- Changed files.
- New instruction.

Không gửi lại toàn bộ lịch sử attempt nếu không cần.

---

# 10. Memory Retrieval Policy

Memory chỉ được retrieve theo relevance.

Không dump toàn bộ `.ant/memory/`.

Memory retrieval nên trả về:

- Memory ID.
- Summary.
- Relevance reason.
- Timestamp.
- Confidence.

---

# 11. Foundation Loading Policy

Foundation và Technical Foundation là tài liệu gốc, nhưng không được load toàn bộ vào mọi task.

Chỉ load khi:

- Task liên quan đến vision.
- Task liên quan đến architecture decision.
- Task có nguy cơ drift.
- Human yêu cầu review foundation.

Mặc định dùng foundation summary ngắn.

---

# 12. Worker Context Package

Mỗi worker nhận một context package có dạng:

```yaml
worker_context:
  task_id: TASK-0001
  worker_type: TestAnt
  mission: "Run tests and summarize failures"
  allowed_files:
    - tests/test_auth.py
    - src/auth/service.py
  forbidden_files:
    - .env
    - .git/
  relevant_memory:
    - id: MEM-001
      summary: "Auth uses JWT, not session-based auth"
  commands_allowed:
    - "pytest tests/test_auth.py"
  output_format: "worker_result_v1"
  context_budget:
    max_input_tokens: 8000
```

---

# 13. Context Compression

Context dài phải được nén theo dạng có cấu trúc.

Không tóm tắt quá mơ hồ.

Tóm tắt tốt phải có:

- Entities.
- Files.
- Decisions.
- Constraints.
- Errors.
- Open questions.

---

# 14. Context Audit

Mỗi model call nên ghi lại:

- Model.
- Input token estimate.
- Output token estimate.
- Context source.
- Files included.
- Reason for inclusion.

Điều này giúp Energy Manager học được cách giảm lãng phí.

---

# 15. Anti-patterns

Cấm các pattern sau:

- “Read the entire repository.”
- “Here is the whole chat history.”
- “Here are all logs from the session.”
- “Give every worker the same context.”
- “Retry by resending everything.”
- “Let sub-agent decide what to read without permission.”

---

# 16. Tiêu chí thành công

Context Policy thành công nếu:

- Worker hoàn thành task với ít file hơn.
- Retry không làm token tăng vô hạn.
- Logs được tóm tắt có cấu trúc.
- Queen biết tại sao context được chọn.
- Human có thể audit model call.
