# ANT-ORCHESTRATOR FOUNDATION

Phiên bản: v0.1  
Trạng thái: Frozen Draft  
Ngôn ngữ: Tiếng Việt

---

# 1. Ant-Orchestrator là gì?

Ant-Orchestrator không phải là một AI model mới.

Ant-Orchestrator không phải là một coding assistant như Claude Code, Codex, Cursor, Gemini CLI hay OpenHands.

Ant-Orchestrator là một hệ điều phối giúp quản lý, phối hợp và tối ưu một hệ sinh thái các AI agent để phát triển phần mềm.

Mục tiêu của Ant-Orchestrator không phải là tạo ra AI mạnh nhất.

Mục tiêu là tạo ra một hệ sinh thái “đàn kiến AI” có khả năng phối hợp, tự trị từng phần và tối ưu năng lượng trong quá trình biến một ý tưởng thành sản phẩm thực tế.

---

# 2. Triết lý cốt lõi

Ant-Orchestrator lấy cảm hứng từ cách đàn kiến hoạt động.

Một con kiến riêng lẻ không cần cực kỳ thông minh. Nhưng khi nhiều con kiến nhỏ phối hợp với nhau thông qua tín hiệu, vai trò, dấu vết và phản hồi từ môi trường, cả đàn có thể giải quyết những việc phức tạp.

Ant-Orchestrator áp dụng nguyên lý này vào AI software development.

Thay vì xây dựng một siêu AI duy nhất, hệ thống sẽ xây dựng một đàn kiến AI gồm nhiều agent nhỏ, mỗi agent có nhiệm vụ chuyên biệt, context giới hạn và vòng đời ngắn.

---

# 3. Vision

> Xây dựng một hệ sinh thái đàn kiến AI lai Cloud–Local, có khả năng tự tổ chức, tự tiến hóa từng phần và biến một ý tưởng thành một sản phẩm thực tế với mức tiêu hao năng lượng và sự chú ý của con người thấp nhất có thể.

Trong đó “năng lượng” bao gồm:

- Token
- API quota
- GPU
- VRAM/RAM
- Thời gian
- Sự chú ý của con người

Human Attention là loại năng lượng cao cấp nhất.

Giảm chi phí tiền bạc chỉ là hệ quả. Mục tiêu gốc là giảm tổng năng lượng bị tiêu hao trong quá trình phát triển phần mềm.

---

# 4. Product Positioning

Ant-Orchestrator là:

> AI Development Operating System.

Hoặc:

> Kubernetes dành cho các AI Coding Agent.

Ant-Orchestrator không thay thế Claude, Codex, Gemini, Ollama hay các coding agent khác.

Ant-Orchestrator quản lý, điều phối và tối ưu cách chúng được sử dụng.

---

# 5. Pain Point chính

Các AI coding agent hiện nay dễ gặp vấn đề context explosion.

Khi dự án lớn dần:

- Context ngày càng phình to.
- Sub-agent liên tục copy context.
- Token tăng theo cấp số nhân.
- API quota cạn rất nhanh.
- Human phải liên tục đọc, sửa, giám sát và restart workflow.

Ví dụ:

```text
Task lớn
↓
Fork 5 sub-agent
↓
5 sub-agent copy toàn bộ context
↓
500k token
↓
Quota cạn kiệt
```

Ant-Orchestrator sinh ra để giải quyết bài toán này.

---

# 6. Ant không cạnh tranh với Claude

Ant-Orchestrator không phải đối thủ của:

- Claude Code
- Codex
- Gemini CLI
- Cursor
- OpenHands
- OpenClaw
- Ollama

Ant-Orchestrator là lớp điều phối phía trên.

Tương tự:

```text
Docker ≠ Kubernetes
Claude ≠ Ant-Orchestrator
```

Claude là một engine/worker/tool mạnh.

Ant-Orchestrator là hệ thống quản lý cách sử dụng các engine/worker/tool đó.

---

# 7. Kiến trúc khái niệm

```text
Human / Vision Owner
↓
Queen Ant
↓
Ant-Orchestrator Core
↓
AI Engine Layer
↓
Specialized Ants / Workers
↓
Tools / Codebase / Tests / Docs
```

---

# 8. Hybrid Cloud–Local

Do hạn chế phần cứng cá nhân, đặc biệt là GPU local, Ant-Orchestrator không theo đuổi Full Local AI trong giai đoạn đầu.

Hệ thống theo đuổi Hybrid Colony.

## Cloud AI

Vai trò:

- Hiểu yêu cầu phức tạp.
- Lập kế hoạch.
- Chia task.
- Review kết quả.
- Ra quyết định lớn.

Ví dụ:

- Claude
- OpenAI
- Gemini

## Local AI

Vai trò:

- Sửa code nhỏ.
- Viết test.
- Chạy test.
- Sửa lỗi đơn giản.
- Update tài liệu.
- Thực hiện task có context hẹp.

Ví dụ:

- Ollama
- Qwen Coder
- DeepSeek local

---

# 9. Không phát triển AI model

Dự án không nghiên cứu AI model.

Dự án không huấn luyện model.

Dự án không fine-tune model trong MVP.

Vai trò của Ant-Orchestrator là thiết kế hệ thống để nhiều AI hiện có phối hợp với nhau hiệu quả hơn.

---

# 10. Không tự xây lại Claude Code

Ant-Orchestrator không xây lại toàn bộ hệ sinh thái của Claude Code.

Những năng lực đã có sẵn ở công cụ khác nên được tái sử dụng qua adapter.

Ví dụ:

- File editing
- Bash
- Git
- Search
- Test runner
- Linter
- Existing CLI agents

Ant-Orchestrator chỉ điều phối và kiểm soát việc sử dụng các năng lực đó.

---

# 11. Triết lý đàn kiến

## 11.1 Một con kiến không được biết toàn bộ tổ kiến

Worker Ant không được đọc toàn bộ codebase nếu không cần thiết.

Worker chỉ được nhận context tối thiểu để hoàn thành nhiệm vụ.

Đây là Context Isolation.

## 11.2 Kiến giao tiếp bằng dấu vết

Worker không tự do trò chuyện trực tiếp với nhau.

Mọi thông tin quan trọng phải đi qua Orchestrator dưới dạng Pheromone.

## 11.3 Kiến làm việc độc lập

Mỗi worker chỉ tập trung vào một nhiệm vụ nhỏ.

Worker không nên giữ state quá lâu.

## 11.4 Kiến có khả năng tự phục hồi

Nếu worker thất bại:

- Ghi log.
- Tóm tắt lỗi.
- Kill worker.
- Spawn worker mới nếu còn budget.
- Retry với context đã tinh gọn.

## 11.5 Kiến tối ưu năng lượng

Mục tiêu không phải là nhanh nhất bằng mọi giá.

Mục tiêu là hiệu quả nhất tính theo chất lượng trên tổng năng lượng tiêu hao.

---

# 12. Ngôn ngữ riêng của hệ thống

| Khái niệm thường | Tên trong Ant |
|---|---|
| Main Agent | Queen |
| Sub Agent | Worker Ant |
| Project | Colony |
| Workspace | Nest |
| Shared Memory | Pheromone |
| Task Queue | Food Queue |
| Token Budget | Energy Budget |
| Retry | Regroup |
| Planner | Scout |
| Scheduler | Colony Manager |

---

# 13. Ultimate Vision

Tầm nhìn dài hạn của Ant-Orchestrator là giảm dần sự chú ý cần thiết của con người để biến một ý tưởng thành một sản phẩm thật.

Con người dịch chuyển vai trò theo thời gian:

```text
Developer
↓
Tech Lead
↓
Architect
↓
Product Owner
↓
Vision Owner
```

Cuối cùng, con người chủ yếu trả lời câu hỏi:

> Chúng ta muốn xây dựng điều gì?

---

# 14. Các pha tiến hóa

## Phase 1 — Assisted Colony

Human giám sát thường xuyên.

Queen lập plan và gọi worker, nhưng human vẫn review nhiều.

## Phase 2 — Semi-Autonomous Colony

Human chỉ xác nhận các quyết định lớn.

Queen biết tự phân rã roadmap, task và retry trong giới hạn.

## Phase 3 — Autonomous Colony

Human cung cấp goal.

Queen tự tạo roadmap, milestone, task, kiểm thử và báo cáo.

## Phase 4 — Self-Evolving Colony

Hệ thống tự học từ kết quả, tự cập nhật roadmap, tự cải thiện worker selection và energy policy.

---

# 15. Tuyên ngôn dự án

Chúng ta không tạo ra AI mạnh hơn.

Chúng ta tạo ra một hệ sinh thái để nhiều AI phối hợp tốt hơn.

Chúng ta không thay thế Claude.

Chúng ta quản lý Claude.

Chúng ta không xây dựng một bộ não khổng lồ.

Chúng ta xây dựng một đàn kiến thông minh.

Mỗi con kiến chỉ cần đủ thông minh để hoàn thành phần việc của nó.

Sức mạnh thực sự đến từ khả năng phối hợp của cả đàn.

Đó là Ant-Orchestrator.
