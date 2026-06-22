# ADR-0003: LiteLLM as LLM Gateway

Ngày: 2026-06-22  
Trạng thái: Accepted

---

## Context

Ant-Orchestrator cần dùng nhiều model/provider: Claude, OpenAI, Gemini, Ollama/local model.

Nếu gọi trực tiếp từng SDK ở nhiều nơi, core sẽ bị phụ thuộc provider và khó quản lý token/cost.

---

## Decision

Dùng LiteLLM hoặc một gateway tương đương để chuẩn hóa việc gọi model.

---

## Reason

LiteLLM giúp:

- Chuẩn hóa provider interface.
- Dễ đổi model.
- Dễ logging usage.
- Phù hợp adapter-first architecture.

---

## Consequences

Tích cực:

- Giảm vendor lock-in.
- Dễ route local/cloud.
- Dễ energy accounting.

Đánh đổi:

- Thêm một dependency.
- Cần kiểm soát lỗi gateway/provider.

---

## Follow-up

- Không để worker gọi SDK provider trực tiếp.
- Ghi usage metadata cho mỗi call.
