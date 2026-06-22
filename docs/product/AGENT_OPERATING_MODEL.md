# AGENT_OPERATING_MODEL.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Tài liệu này định nghĩa mô hình vận hành của các agent trong Ant-Orchestrator.

Mục tiêu là trả lời:

- Queen là ai?
- Worker Ant là ai?
- Worker được phép làm gì?
- Worker không được phép làm gì?
- Thông tin đi qua hệ thống như thế nào?

---

# 2. Nguyên tắc chung

Ant-Orchestrator không vận hành theo kiểu một agent lớn làm tất cả.

Hệ thống vận hành theo mô hình đàn kiến:

```text
Human / Vision Owner
↓
Queen
↓
Orchestrator Core
↓
Specialized Ants
↓
Tools
```

Queen giữ vai trò điều phối và ra quyết định.

Worker Ant thực hiện các nhiệm vụ nhỏ, context hẹp, vòng đời ngắn.

---

# 3. Human / Vision Owner

Human là người giữ vision cuối cùng.

Human chịu trách nhiệm:

- Định nghĩa mục tiêu sản phẩm.
- Chốt foundation.
- Chốt technical foundation.
- Phê duyệt quyết định rủi ro.
- Review các thay đổi lớn.
- Điều chỉnh hướng đi khi vision thay đổi.

Human không nên phải:

- Đọc toàn bộ logs dài.
- Tự gom context cho từng worker.
- Tự restart workflow thủ công quá nhiều.
- Tự kiểm tra những việc máy có thể kiểm tra.

---

# 4. Queen Ant

Queen là agent điều phối cấp cao.

Trong MVP, Queen thường dùng cloud model.

## 4.1 Trách nhiệm của Queen

Queen có 5 trách nhiệm chính:

1. Strategist
2. Roadmap Evolver
3. Colony Manager
4. Energy Optimizer
5. Performance Evaluator

---

## 4.2 Queen như Strategist

Queen hiểu mục tiêu dài hạn, foundation và technical foundation.

Queen phải đảm bảo mọi quyết định không đi lệch vision.

---

## 4.3 Queen như Roadmap Evolver

Queen có thể đề xuất cập nhật roadmap khi phát hiện task mới, rủi ro mới hoặc dependency mới.

Trong MVP, Queen chỉ đề xuất. Human phê duyệt thay đổi roadmap lớn.

---

## 4.4 Queen như Colony Manager

Queen phân rã task thành micro-task.

Queen chọn worker phù hợp.

Queen theo dõi trạng thái worker.

Queen quyết định retry, regroup hoặc escalate.

---

## 4.5 Queen như Energy Optimizer

Queen phải luôn tự hỏi:

- Task này có cần cloud model không?
- Có thể dùng local worker không?
- Có thể dùng cache/memory thay vì gọi model không?
- Có thể giảm context không?
- Có cần hỏi human không hay có thể tự xử lý?

---

## 4.6 Queen như Performance Evaluator

Queen đánh giá worker sau mỗi task.

Chỉ số có thể gồm:

- Success rate.
- Retry count.
- Energy usage.
- Completion time.
- Quality score.
- Trust score.

---

# 5. Worker Ant

Worker Ant là agent chuyên biệt.

Worker chỉ nhận một nhiệm vụ nhỏ.

Worker không nên biết toàn bộ project.

Worker không tự quyết định chiến lược.

Worker không tự ý mở rộng phạm vi task.

---

# 6. Worker ban đầu trong MVP

## 6.1 Documentation Ant

Nhiệm vụ:

- Viết tài liệu.
- Sửa tài liệu.
- Tóm tắt task.
- Ghi handoff.
- Cập nhật decision log theo yêu cầu.

Không được:

- Tự sửa code production nếu không được giao.
- Tự thay đổi foundation đã frozen.
- Tự ghi memory dài hạn nếu không qua Memory Writer.

---

## 6.2 Test Ant

Nhiệm vụ:

- Chạy test.
- Đọc test failure.
- Tóm tắt lỗi.
- Đề xuất fix.
- Viết test nhỏ khi được giao.
- Xác minh regression.

Không được:

- Tự xóa test để làm pass.
- Tự sửa business logic lớn.
- Tự thay đổi test command.
- Tự bỏ qua lỗi test.

---

# 7. Worker tương lai

Các worker có thể bổ sung sau MVP:

- Frontend Ant
- Backend Ant
- DevOps Ant
- Security Ant
- Research Ant
- Product Ant
- Design Ant
- Refactor Ant
- Migration Ant

Mỗi worker mới phải có:

- Mission.
- Input contract.
- Output contract.
- Permission boundary.
- Energy budget.
- Evaluation metric.

---

# 8. Quy tắc giao tiếp

Worker không giao tiếp trực tiếp với worker khác.

Worker output phải đi qua Orchestrator.

Thông tin dùng chung phải được ghi thành Pheromone hoặc Memory.

Không dùng chat tự do giữa các worker vì sẽ gây mất kiểm soát context.

---

# 9. Vòng đời worker

```text
Spawn
↓
Receive scoped context
↓
Execute task
↓
Return result
↓
Summarize evidence
↓
Terminate
```

Worker không nên sống quá lâu.

Worker càng sống lâu càng dễ tích lũy context thừa.

---

# 10. Permission boundary

Mỗi worker cần được cấp quyền rõ ràng:

- Được đọc file nào?
- Được sửa file nào?
- Được chạy command nào?
- Được gọi model nào?
- Budget token/time là bao nhiêu?
- Có được retry không?

Mọi quyền mặc định là deny.

Orchestrator cấp quyền theo task.

---

# 11. Escalation

Worker phải escalate về Queen khi:

- Context không đủ.
- Task vượt phạm vi.
- Phát hiện rủi ro kiến trúc.
- Test fail không rõ nguyên nhân.
- Cần sửa file ngoài permission.
- Cần gọi model đắt hơn.
- Cần human approval.

---

# 12. Output bắt buộc của worker

Worker output không chỉ là kết quả.

Worker phải trả về:

- Summary.
- Files read.
- Files changed.
- Commands run.
- Result.
- Evidence.
- Risk.
- Suggested next step.

---

# 13. Nguyên tắc chống drift

Worker không được tự tạo vision mới.

Worker không được đổi technical foundation.

Queen phải đối chiếu quyết định lớn với Foundation và Technical Foundation.

Mọi thay đổi lớn cần Decision Log hoặc ADR.
