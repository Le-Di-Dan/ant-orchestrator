# DECISION_LOG.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Decision Log lưu các quyết định đã chốt trong dự án Ant-Orchestrator.

Mục tiêu là tránh tranh luận lại từ đầu và giúp mọi agent đối chiếu quyết định mới với foundation.

---

# 2. Nguyên tắc

Mọi quyết định lớn phải có:

- ID.
- Ngày.
- Quyết định.
- Lý do.
- Hệ quả.
- Trạng thái.

Quyết định kiến trúc lớn nên có ADR riêng trong thư mục `adr/`.

---

# 3. Decisions

## DEC-0001 — Ant-Orchestrator là AI Development Operating System

Trạng thái: Accepted

Ant-Orchestrator không phải AI model, không phải Claude replacement, không phải coding assistant đơn lẻ.

Ant-Orchestrator là hệ điều phối cho các AI coding agent/tool.

---

## DEC-0002 — Vision là Self-Evolving Hybrid Cloud–Local AI Colony

Trạng thái: Accepted

Hệ thống hướng tới đàn kiến AI lai cloud-local, tự trị tăng dần, tối ưu energy và human attention.

---

## DEC-0003 — Không phát triển AI model trong MVP

Trạng thái: Accepted

Không training, không fine-tuning, không nghiên cứu model trong MVP.

Tập trung điều phối AI hiện có.

---

## DEC-0004 — Python-first core

Trạng thái: Accepted

Core dùng Python.

Xem `adr/ADR-0001-python-first-core.md`.

---

## DEC-0005 — FastAPI daemon/API

Trạng thái: Accepted

Daemon/API dùng FastAPI.

---

## DEC-0006 — Typer CLI

Trạng thái: Accepted

CLI dùng Typer.

---

## DEC-0007 — LangGraph-first workflow

Trạng thái: Accepted

Workflow/state machine ưu tiên LangGraph.

Xem `adr/ADR-0002-langgraph-first.md`.

---

## DEC-0008 — LiteLLM as LLM Gateway

Trạng thái: Accepted

Gọi model qua LiteLLM/gateway abstraction.

Xem `adr/ADR-0003-litellm-gateway.md`.

---

## DEC-0009 — Ollama local worker-first

Trạng thái: Accepted

Worker local ưu tiên Ollama/Qwen Coder khi task hẹp.

Xem `adr/ADR-0004-ollama-local-worker-first.md`.

---

## DEC-0010 — SQLite initial local state

Trạng thái: Accepted

MVP dùng SQLite trước, Postgres để sau.

Xem `adr/ADR-0005-sqlite-initial-state.md`.

---

## DEC-0011 — `.ant/` workspace per project

Trạng thái: Accepted

Mỗi project có `.ant/` riêng để lưu state, task, logs, memory, pheromone.

---

## DEC-0012 — MVP Autonomy Level 1

Trạng thái: Accepted

Human vẫn giám sát và phê duyệt quyết định lớn.

Hệ thống tự động hóa vòng lặp task nhỏ, test, retry, review có giới hạn.

---

## DEC-0013 — Worker đầu tiên là Documentation Ant và Test Ant

Trạng thái: Accepted

MVP không mở quá nhiều worker từ đầu.

Bắt đầu với Documentation Ant và Test Ant để chứng minh vòng lặp điều phối.

---

# 4. Decision Template

```markdown
## DEC-XXXX — Title

Ngày: YYYY-MM-DD  
Trạng thái: Proposed | Accepted | Superseded | Rejected

### Context

### Decision

### Reason

### Consequences

### Related ADR
```
