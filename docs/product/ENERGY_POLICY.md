# ENERGY_POLICY.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Energy Policy quy định cách Ant-Orchestrator quản lý năng lượng.

Trong Ant-Orchestrator, năng lượng không chỉ là tiền.

Năng lượng bao gồm:

- Token
- API quota
- GPU
- VRAM/RAM
- Thời gian
- Human Attention

Human Attention là năng lượng cao cấp nhất.

---

# 2. Thứ bậc năng lượng

```text
Level 1: Token
Level 2: API quota / money
Level 3: GPU / VRAM / RAM
Level 4: Time
Level 5: Human Attention
```

Một quyết định tốt không chỉ tiết kiệm token.

Một quyết định tốt phải giảm tổng năng lượng tiêu hao, đặc biệt là sự chú ý của con người.

---

# 3. Nguyên tắc chung

Queen và Energy Manager phải luôn hỏi:

1. Có cần gọi model không?
2. Có thể dùng cache không?
3. Có thể dùng memory không?
4. Có thể dùng local model không?
5. Có cần cloud model không?
6. Có cần human không?
7. Có thể giảm context không?
8. Có thể chia task nhỏ hơn không?

---

# 4. Model Routing Policy

## 4.1 Local-first cho task hẹp

Dùng local model/Ollama trước khi:

- Task nhỏ.
- Context rõ.
- Rủi ro thấp.
- Không cần reasoning kiến trúc.
- Output có thể kiểm chứng bằng test/lint.

Ví dụ:

- Update markdown.
- Tạo test đơn giản.
- Tóm tắt log.
- Sửa lỗi nhỏ.

## 4.2 Cloud model cho task cấp cao

Dùng cloud model khi:

- Cần lập kế hoạch.
- Cần review kiến trúc.
- Cần phân rã task.
- Cần đánh giá trade-off.
- Local model fail nhiều lần.
- Task có rủi ro cao.

## 4.3 Escalation

Local → Cloud khi:

- Retry vượt budget.
- Output không đạt quality gate.
- Test fail không giải thích được.
- Context cần hiểu nhiều module.
- Có dấu hiệu hallucination.

---

# 5. Token Budget

Mỗi task phải có token budget.

Ví dụ:

```yaml
energy_budget:
  max_total_tokens: 50000
  max_planning_tokens: 12000
  max_worker_tokens: 20000
  max_review_tokens: 12000
  max_retry_tokens: 6000
```

Nếu vượt budget, Queen phải:

- Dừng.
- Tóm tắt trạng thái.
- Đề xuất cách tiếp tục.
- Xin human approval nếu cần.

---

# 6. Retry Budget

Retry không được vô hạn.

MVP đề xuất:

```yaml
retry_policy:
  max_worker_retries: 2
  max_test_retries: 2
  require_escalation_after: 2
```

Retry phải thay đổi chiến lược.

Không retry bằng cách gửi lại cùng prompt và cùng context.

---

# 7. Human Attention Budget

Human không nên bị hỏi quá nhiều.

Chỉ hỏi human khi:

- Có quyết định sản phẩm.
- Có thay đổi architecture lớn.
- Có hành động phá hủy.
- Có rủi ro mất dữ liệu.
- Có trade-off không thể tự quyết.
- Budget vượt ngưỡng.

Không hỏi human những việc có thể kiểm chứng bằng test/lint/log.

---

# 8. Cache Policy

Trước khi gọi model, hệ thống nên kiểm tra:

- Task tương tự đã từng làm chưa?
- Memory có câu trả lời chưa?
- Previous summary có dùng lại được không?
- File relevance đã có cache chưa?

Cache không phải source of truth.

Cache chỉ là công cụ tiết kiệm năng lượng.

---

# 9. Energy Logging

Mỗi task phải ghi:

- Model used.
- Local/cloud.
- Estimated input tokens.
- Estimated output tokens.
- Runtime.
- Retry count.
- Human interruptions/questions.
- Test runs.
- Final status.

---

# 10. Ant Efficiency Score

Có thể dùng chỉ số AES để đánh giá worker:

```text
AES = Quality Score / (Energy × Time × Retry Count)
```

Trong MVP, AES chỉ cần ghi dạng experimental.

Không dùng AES để tự động loại worker khi chưa đủ dữ liệu.

---

# 11. Energy Decision Examples

## Ví dụ 1: Update tài liệu

Nên dùng Documentation Ant local.

Không cần cloud Queen nếu task rõ.

## Ví dụ 2: Thiết kế architecture mới

Dùng Queen cloud.

Sau đó Documentation Ant local ghi ADR.

## Ví dụ 3: Test fail nhỏ

Test Ant local đọc failure summary.

Nếu fail 2 lần, escalate Queen.

## Ví dụ 4: Human phải đọc log 3000 dòng

Sai.

Worker phải tóm tắt log trước.

---

# 12. Anti-patterns

- Dùng Claude cho mọi task nhỏ.
- Dùng local model cho quyết định kiến trúc lớn.
- Retry vô hạn.
- Gửi toàn bộ repo vào prompt.
- Hỏi human quá sớm.
- Hỏi human quá muộn khi đã phá vỡ scope.
- Không ghi token/log nên không học được gì.

---

# 13. Tiêu chí thành công

Energy Policy thành công nếu:

- Token giảm theo thời gian.
- Retry giảm theo thời gian.
- Human ít phải can thiệp hơn.
- Local model xử lý được nhiều task nhỏ.
- Cloud model được dùng đúng nơi.
- Task vẫn đạt quality gate.
