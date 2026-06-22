# MEMORY_AND_PHEROMONE_SPEC.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Tài liệu này định nghĩa Colony Memory và Pheromone trong Ant-Orchestrator.

Mục tiêu là giúp hệ thống nhớ những điều quan trọng mà không biến memory thành bãi rác context.

---

# 2. Phân biệt Memory và Pheromone

## Colony Memory

Memory là tri thức dài hạn.

Ví dụ:

- Quyết định kỹ thuật đã chốt.
- Convention của project.
- Kiến trúc đã chọn.
- Known issue quan trọng.
- Pattern thành công.

## Pheromone

Pheromone là dấu vết ngắn hạn/trung hạn phục vụ điều phối.

Ví dụ:

- File A liên quan đến lỗi X.
- Test B đang fail.
- Worker C vừa sửa module D.
- Có risk ở migration E.

---

# 3. Nguyên tắc Memory

Memory phải:

- Ngắn.
- Có cấu trúc.
- Có nguồn gốc.
- Có timestamp.
- Có confidence.
- Có điều kiện áp dụng.

Memory không phải log.

Memory không phải transcript.

Memory không phải nơi dump toàn bộ response của model.

---

# 4. Memory Types

Các loại memory ban đầu:

```text
project_fact
technical_decision
coding_convention
architecture_summary
known_issue
successful_pattern
human_preference
risk_note
```

---

# 5. Memory Record Format

Ví dụ:

```yaml
id: MEM-0001
type: technical_decision
title: "Core uses Python-first architecture"
summary: "Ant-Orchestrator core will be built in Python, with FastAPI daemon and Typer CLI."
source: "TECHNICAL_FOUNDATION.md"
created_at: "2026-06-22T00:00:00+07:00"
confidence: high
applies_to:
  - core
  - api
  - cli
tags:
  - python
  - foundation
```

---

# 6. Pheromone Types

Các loại pheromone ban đầu:

```text
file_relevance
test_failure
worker_note
risk_signal
next_step
blocked_reason
context_hint
```

---

# 7. Pheromone Record Format

Ví dụ:

```yaml
id: PHER-0001
type: test_failure
task_id: TASK-0003
summary: "Auth tests fail because JWT secret is missing in test environment."
files:
  - tests/test_auth.py
  - src/auth/config.py
created_by: TestAnt
created_at: "2026-06-22T00:00:00+07:00"
expires_after: "7d"
confidence: medium
```

---

# 8. Memory Write Policy

Worker không được tự ý ghi trực tiếp memory dài hạn.

Worker có thể đề xuất memory.

Memory Writer hoặc Queen quyết định ghi.

Một thông tin được ghi memory khi:

- Có giá trị tái sử dụng.
- Sẽ còn đúng trong tương lai.
- Ảnh hưởng đến quyết định sau này.
- Không phải chi tiết tạm thời.

---

# 9. Pheromone Write Policy

Worker có thể ghi pheromone nếu được cấp quyền.

Pheromone nên có TTL.

Pheromone hết hạn có thể archive hoặc xóa.

---

# 10. Memory Retrieval

Memory retrieval phải theo relevance.

Không dump toàn bộ memory vào prompt.

Kết quả retrieval nên gồm:

- ID.
- Summary.
- Why relevant.
- Confidence.
- Source.

---

# 11. Memory Update

Memory có thể được:

- Added.
- Amended.
- Deprecated.
- Superseded.

Không nên xóa memory quan trọng nếu nó là decision history.

Nếu decision thay đổi, tạo memory mới và đánh dấu memory cũ là superseded.

---

# 12. Memory Garbage Collection

Cần định kỳ dọn memory rác.

Memory rác gồm:

- Trùng lặp.
- Quá chi tiết.
- Không còn đúng.
- Không còn liên quan.
- Chỉ là log tạm thời.

---

# 13. Decision Trace

Các quyết định lớn phải có trace:

- Context.
- Options considered.
- Decision.
- Reason.
- Consequences.
- Date.
- Approver.

Decision lớn nên ghi vào ADR, không chỉ memory.

---

# 14. Handoff vs Memory

Handoff là báo cáo sau task/session.

Memory là tri thức được chọn lọc từ handoff.

Không phải mọi handoff đều trở thành memory.

---

# 15. MVP Implementation

Trong MVP, có thể bắt đầu đơn giản:

```text
.ant/memory/memory.yaml
.ant/pheromones/*.yaml
.ant/handoff/*.md
```

Sau đó đồng bộ với SQLite khi cần query tốt hơn.

---

# 16. Anti-patterns

- Ghi toàn bộ chat vào memory.
- Ghi mọi log vào memory.
- Ghi memory không có source.
- Memory không có timestamp.
- Không có cơ chế deprecate.
- Worker tự ý ghi decision dài hạn.
