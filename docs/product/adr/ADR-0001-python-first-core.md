# ADR-0001: Python-first Core

Ngày: 2026-06-22  
Trạng thái: Accepted

---

## Context

Ant-Orchestrator cần một core đủ linh hoạt để xây orchestration workflow, model adapter, CLI, daemon/API, context router, memory và energy manager.

Dự án cần tích hợp nhiều công cụ AI/agent/tooling hiện có.

---

## Decision

Core của Ant-Orchestrator sẽ dùng Python-first.

---

## Reason

Python phù hợp vì:

- Hệ sinh thái AI mạnh.
- Tích hợp LangGraph/LangChain/LiteLLM/Ollama thuận lợi.
- Dễ viết orchestration logic.
- Dễ xây CLI bằng Typer.
- Dễ xây daemon/API bằng FastAPI.
- Phù hợp MVP personal infrastructure.

---

## Consequences

Tích cực:

- Tốc độ phát triển nhanh.
- Dễ tích hợp AI stack.
- Dễ prototype workflow.

Đánh đổi:

- Cần quản lý dependency Python cẩn thận.
- Cần discipline về typing, test, module boundary.

---

## Follow-up

- Dùng `pyproject.toml`.
- Bật type checking nếu phù hợp.
- Tách module core/api/cli/workflows/adapters rõ ràng.
