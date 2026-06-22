# ADR-0004: Ollama Local Worker-first

Ngày: 2026-06-22  
Trạng thái: Accepted

---

## Context

Ant-Orchestrator có mục tiêu tối ưu token, quota và chi phí cloud.

Phần cứng local có giới hạn, nhưng vẫn có thể chạy model nhỏ/phù hợp qua Ollama cho task hẹp.

---

## Decision

Worker nhỏ trong MVP ưu tiên dùng Ollama/local model trước khi escalate lên cloud.

---

## Reason

Local worker phù hợp cho:

- Documentation update.
- Test summary.
- Small code fix.
- Log summarization.
- Low-risk task.

Cloud model giữ vai trò Queen/reasoning/review.

---

## Consequences

Tích cực:

- Giảm chi phí cloud.
- Giảm quota usage.
- Tăng khả năng chạy nhiều task nhỏ.

Đánh đổi:

- Chất lượng local model không ổn định bằng cloud.
- Cần retry/escalation policy.
- Cần context nhỏ và rõ.

---

## Follow-up

- Bắt đầu với Qwen Coder hoặc model coding local phù hợp.
- Ghi success/failure để đánh giá worker.
