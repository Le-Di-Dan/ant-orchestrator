# ADR-0002: LangGraph-first Workflow

Ngày: 2026-06-22  
Trạng thái: Accepted

---

## Context

Ant-Orchestrator cần quản lý workflow gồm nhiều bước: plan, split, context package, worker execution, validation, review, retry, memory persistence.

Workflow có state, nhánh rẽ, retry và điều kiện.

---

## Decision

MVP ưu tiên LangGraph làm nền tảng workflow/state machine.

---

## Reason

LangGraph phù hợp vì:

- Biểu diễn workflow dạng graph.
- Có state rõ ràng.
- Phù hợp với agent orchestration.
- Dễ mở rộng retry/escalation.

LangChain/CrewAI không bị cấm, nhưng không phải foundation chính trong MVP.

---

## Consequences

Tích cực:

- Workflow rõ ràng hơn chain tuyến tính.
- Dễ kiểm soát state.
- Dễ audit các bước.

Đánh đổi:

- Cần học và thiết kế graph cẩn thận.
- Không nên over-engineer graph ngay từ đầu.

---

## Follow-up

- Bắt đầu với một graph MVP đơn giản.
- Không tạo quá nhiều node trước khi cần.
