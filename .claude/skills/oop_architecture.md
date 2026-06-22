# Skill — OOP Architecture

## Mục tiêu

Đảm bảo code có cấu trúc tốt, dễ mở rộng, dễ test và phù hợp với hướng Ant-Orchestrator là core infrastructure.

## Nguyên tắc chính

### 1. Single Responsibility

Mỗi class/module chỉ có một trách nhiệm rõ ràng.
Không gom orchestration, persistence, API call, validation vào cùng một class.

### 2. Dependency Inversion

Core logic không phụ thuộc trực tiếp vào vendor cụ thể.
Ví dụ:

- Không để core gọi trực tiếp OpenAI SDK.
- Core gọi qua interface `LLMClient`, `ModelAdapter`, `WorkerAdapter`.

### 3. Interface trước implementation

Với các thành phần có khả năng thay đổi, phải thiết kế contract trước.
Ví dụ:

- `AgentAdapter`
- `TaskStore`
- `MemoryStore`
- `EnergyMeter`
- `ContextProvider`

### 4. Composition hơn inheritance

Chỉ dùng inheritance khi có quan hệ “is-a” thật sự.
Ưu tiên inject dependency và compose behavior.

### 5. Domain rõ ràng

Tên class phải phản ánh domain Ant:

- `QueenPlanner`
- `WorkerAnt`
- `EnergyBudget`
- `PheromoneMemory`
- `TaskAssignment`
- `ColonyState`

Không dùng tên mơ hồ như `Manager`, `Helper`, `Util` nếu có thể đặt tên domain tốt hơn.

## Điều cấm

- God class.
- Static global state không kiểm soát.
- Function quá dài.
- Module vừa validate, vừa execute, vừa persist, vừa report.
- Gọi trực tiếp provider cụ thể từ domain core.

## Checklist thiết kế

Trước khi hoàn thành, tự hỏi:

1. Class này có đúng một trách nhiệm không?
2. Có phụ thuộc vendor cụ thể không?
3. Có test được bằng mock/fake không?
4. Có thể thêm adapter mới mà không sửa core không?
5. Tên class có phản ánh domain không?
