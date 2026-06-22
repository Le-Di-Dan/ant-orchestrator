# MVP_SCOPE.md

Phiên bản: v0.1  
Trạng thái: Frozen Draft

---

# 1. Mục tiêu MVP

MVP của Ant-Orchestrator không nhằm chứng minh fully autonomous software engineer.

MVP chỉ cần chứng minh một vòng lặp điều phối AI có kiểm soát, tiết kiệm context và tiết kiệm năng lượng hơn cách dùng một agent lớn đọc toàn bộ project.

---

# 2. MVP Success Loop

MVP thành công nếu chứng minh được vòng lặp:

```text
Human tạo task
↓
Queen cloud model lập kế hoạch
↓
Queen chia micro-task
↓
Local worker thực hiện task nhỏ
↓
Test Ant chạy test hoặc validation
↓
Nếu fail thì retry có giới hạn
↓
Queen review
↓
Ghi log/memory/handoff
```

---

# 3. MVP Autonomy Level

MVP dùng Autonomy Level 1.

Nghĩa là:

- Human vẫn là người giao task.
- Human vẫn phê duyệt thay đổi lớn.
- Hệ thống có thể tự retry trong giới hạn.
- Hệ thống có thể tự chạy validation an toàn.
- Hệ thống không tự deploy.
- Hệ thống không tự merge thay đổi rủi ro.

---

# 4. MVP In Scope

## 4.1 CLI cơ bản

Cần có CLI để:

- Init project.
- Tạo task.
- Xem trạng thái task.
- Xem logs.
- Chạy workflow.

## 4.2 FastAPI daemon cơ bản

Cần có API để:

- Submit task.
- Inspect task.
- Inspect worker run.
- Inspect logs.

UI chưa bắt buộc.

## 4.3 LangGraph workflow

Cần có graph tối thiểu:

- Plan node.
- Context package node.
- Worker execution node.
- Validation node.
- Review node.
- Memory/handoff node.

## 4.4 LiteLLM gateway

Cần có abstraction để gọi model.

Trong MVP có thể bắt đầu với:

- OpenAI hoặc Claude cho Queen.
- Ollama cho local worker.

## 4.5 Ollama worker

Cần chứng minh local worker có thể làm task nhỏ.

## 4.6 SQLite state

Cần lưu:

- Task.
- Worker run.
- Status.
- Logs summary.
- Energy usage.

## 4.7 `.ant/` workspace

Mỗi project có `.ant/` để lưu state, memory, logs, task.

## 4.8 Documentation Ant

Worker đầu tiên để tạo/sửa/tóm tắt tài liệu.

## 4.9 Test Ant

Worker thứ hai để chạy test, tóm tắt lỗi và xác minh.

## 4.10 Context Policy enforcement cơ bản

MVP phải có giới hạn context.

Không được gửi toàn bộ repo cho worker mặc định.

## 4.11 Energy logging cơ bản

MVP phải ghi lại model usage và retry count.

---

# 5. MVP Out of Scope

MVP chưa làm:

- Full autonomous roadmap evolution.
- Multi-user web platform.
- Distributed worker cluster.
- Production deployment automation.
- Auto-merge không cần human.
- Auto-deploy production.
- Fine-tuning model.
- Training model.
- Marketplace plugin.
- Complex UI.
- Worker performance learning phức tạp.
- Self-healing cluster.
- Long-term autonomous execution ngày/đêm.

---

# 6. MVP Workers

Chỉ cần 2 worker:

1. Documentation Ant
2. Test Ant

Frontend/Backend/DevOps/Security Ant để sau.

---

# 7. MVP Quality Gates

Một task MVP được coi là hoàn thành nếu:

- Có task record.
- Có plan.
- Có context package.
- Có worker result.
- Có validation hoặc lý do không validate được.
- Có review summary.
- Có handoff.
- Có energy summary cơ bản.

---

# 8. MVP Demo Scenario

Scenario đề xuất:

```text
Human: Hãy tạo tài liệu Context Policy cho project.
↓
Queen: Lập plan và giao Documentation Ant.
↓
Context Router: Cấp Foundation summary + Technical Foundation summary.
↓
Documentation Ant: Tạo CONTEXT_POLICY.md.
↓
Validation: Kiểm tra file tồn tại, có các section bắt buộc.
↓
Queen: Review tài liệu có bám vision không.
↓
Memory Writer: Ghi decision/context rule quan trọng.
↓
Handoff: Báo cáo hoàn thành.
```

---

# 9. MVP Non-goals

MVP không cần nhanh nhất.

MVP không cần hoàn hảo.

MVP không cần nhiều agent.

MVP không cần UI đẹp.

MVP chỉ cần chứng minh kiến trúc điều phối đúng hướng.

---

# 10. Điều kiện chuyển sang Phase 2

Có thể chuyển sang Phase 2 khi:

- Vòng lặp task chạy ổn định.
- Context package giúp giảm token rõ ràng.
- Local worker xử lý được task nhỏ.
- Retry có kiểm soát.
- Handoff/memory hữu ích.
- Human ít phải can thiệp hơn so với workflow thủ công.
