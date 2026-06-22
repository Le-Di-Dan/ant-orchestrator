# WORKFLOW_SPEC.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Workflow Spec mô tả vòng đời task trong Ant-Orchestrator.

Mục tiêu là đảm bảo mọi task đều đi qua một quy trình có kiểm soát, có context boundary, có energy budget, có test/review và có memory/handoff sau khi hoàn thành.

---

# 2. Workflow tổng quát

```text
Receive Task
↓
Classify Task
↓
Plan
↓
Split into Micro-tasks
↓
Prepare Context Package
↓
Assign Worker
↓
Execute
↓
Validate / Test
↓
Review
↓
Persist Memory / Pheromone
↓
Handoff
```

---

# 3. Task Intake

Task có thể đến từ:

- CLI.
- API.
- UI tương lai.
- Human prompt.
- Roadmap Evolver tương lai.

Task intake phải tạo một Task Record.

Ví dụ:

```yaml
task_id: TASK-0001
title: "Create Context Policy document"
source: human
status: created
priority: normal
created_at: "2026-06-22T00:00:00+07:00"
```

---

# 4. Task Classification

Queen hoặc Orchestrator phân loại task.

Loại task ban đầu:

- documentation
- test
- code_fix
- research
- planning
- review
- refactor
- unknown

Classification giúp chọn worker và model.

---

# 5. Planning

Queen tạo plan ngắn.

Plan phải gồm:

- Goal.
- Constraints.
- Expected output.
- Risk.
- Worker candidates.
- Validation method.

Plan không được quá dài nếu task nhỏ.

---

# 6. Task Splitting

Task lớn phải chia thành micro-task.

Một micro-task tốt có đặc điểm:

- Một mục tiêu rõ.
- Có acceptance criteria.
- Có file scope nhỏ.
- Có thể validate.
- Có thể retry độc lập.

Ví dụ:

```text
TASK-0001 Create operating docs
├── TASK-0001.1 Create Context Policy
├── TASK-0001.2 Create Agent Operating Model
├── TASK-0001.3 Create Workflow Spec
└── TASK-0001.4 Package docs
```

---

# 7. Context Preparation

Trước khi worker chạy, Context Router tạo context package.

Context package phải tuân thủ `CONTEXT_POLICY.md`.

Không worker nào được nhận raw toàn bộ project trừ khi được phép rõ ràng.

---

# 8. Worker Assignment

Orchestrator chọn worker dựa trên:

- Task type.
- Worker capability.
- Energy policy.
- Historical trust score.
- Availability.
- Required tool permission.

Trong MVP:

- documentation → Documentation Ant
- test → Test Ant
- planning/review → Queen

---

# 9. Execution

Worker thực hiện task trong permission boundary.

Worker phải ghi:

- Files read.
- Files changed.
- Commands run.
- Errors.
- Result.

Worker không được mở rộng scope nếu không báo Queen.

---

# 10. Validation

Validation phụ thuộc task type.

Ví dụ:

- Documentation: markdown exists, required sections present.
- Code fix: tests pass.
- Test task: test command executed, result captured.
- Planning: output có acceptance criteria.

Validation nên tự động nếu có thể.

---

# 11. Review

Review có thể do:

- Queen.
- Dedicated Review Ant tương lai.
- Human.

Trong MVP, review quan trọng nên dùng Queen cloud hoặc human.

Review phải kiểm tra:

- Đúng task không?
- Có vượt scope không?
- Có phá constraint không?
- Có đủ evidence không?
- Có cần retry không?

---

# 12. Retry / Regroup

Nếu fail:

```text
Failure
↓
Summarize failure
↓
Check retry budget
↓
Adjust context/strategy
↓
Retry or escalate
```

Retry không được lặp lại cùng context và cùng strategy.

Nếu retry budget hết, Queen phải dừng và báo cáo.

---

# 13. Memory / Pheromone Persistence

Sau task, hệ thống quyết định ghi gì:

## Pheromone

Dấu vết ngắn hạn:

- File liên quan.
- Test fail.
- Risk.
- Next step.

## Memory

Tri thức dài hạn:

- Decision.
- Convention.
- Architecture fact.
- Known issue.
- Successful pattern.

Không phải mọi log đều trở thành memory.

---

# 14. Handoff

Mỗi task hoàn thành phải có handoff ngắn.

Handoff gồm:

- Task summary.
- What changed.
- Validation.
- Open issues.
- Suggested next steps.
- Energy summary.

---

# 15. Task Status

Trạng thái đề xuất:

```text
created
classified
planned
split
assigned
running
validating
reviewing
completed
failed
blocked
cancelled
```

---

# 16. Quality Gates

Một task không được đánh dấu completed nếu thiếu:

- Output chính.
- Validation evidence.
- Worker summary.
- Error/risk nếu có.
- Handoff.

---

# 17. MVP Workflow

MVP chỉ cần workflow sau:

```text
Human submit task
↓
Queen plan
↓
Queen split small tasks
↓
Documentation Ant hoặc Test Ant execute
↓
Run validation
↓
Queen review
↓
Write handoff
```

Chưa cần workflow tự tiến hóa đầy đủ.
