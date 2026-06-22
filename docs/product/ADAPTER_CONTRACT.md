# ADAPTER_CONTRACT.md

Phiên bản: v0.1  
Trạng thái: Draft

---

# 1. Mục tiêu

Adapter Contract quy định cách Ant-Orchestrator tích hợp với các AI engine, CLI agent và tool bên ngoài.

Mục tiêu là tránh phụ thuộc cứng vào một provider.

Ant-Orchestrator phải có thể thay đổi engine mà không viết lại core workflow.

---

# 2. Nguyên tắc Adapter-first

Core không gọi trực tiếp OpenAI, Claude, Gemini, Ollama hay Claude CLI ở nhiều nơi.

Mọi tích hợp phải đi qua adapter.

Adapter chịu trách nhiệm:

- Chuẩn hóa input.
- Gọi provider/tool.
- Chuẩn hóa output.
- Ghi usage.
- Xử lý lỗi.
- Enforce timeout/budget.

---

# 3. Adapter Types

Các loại adapter ban đầu:

```text
LLMAdapter
CLIAdapter
ToolAdapter
TestRunnerAdapter
FileSystemAdapter
GitAdapter
```

---

# 4. LLM Adapter Contract

LLM Adapter cần hỗ trợ interface khái niệm:

```python
class LLMAdapter:
    def complete(self, request: LLMRequest) -> LLMResponse:
        pass
```

## LLMRequest

```yaml
model: "gpt-4o-mini"
messages: []
system_prompt: "..."
context_package: {}
temperature: 0.2
max_output_tokens: 4000
timeout_seconds: 120
metadata:
  task_id: TASK-0001
  worker_type: DocumentationAnt
```

## LLMResponse

```yaml
text: "..."
model: "gpt-4o-mini"
provider: "openai"
usage:
  input_tokens: 1000
  output_tokens: 800
  total_tokens: 1800
finish_reason: "stop"
error: null
```

---

# 5. Required LLM Adapters

## 5.1 OpenAI Adapter

Dùng cho Queen hoặc review nếu cần.

## 5.2 Claude Adapter

Dùng cho reasoning mạnh hoặc review chất lượng cao.

## 5.3 Gemini Adapter

Dự phòng hoặc dùng theo cost/performance.

## 5.4 Ollama Adapter

Dùng cho local worker.

---

# 6. CLI Adapter Contract

CLI Adapter dùng để gọi các tool như Claude CLI hoặc agent CLI khác.

```python
class CLIAdapter:
    def run(self, request: CLIRequest) -> CLIResponse:
        pass
```

## CLIRequest

```yaml
command: "claude"
args: []
working_dir: "/path/to/project"
stdin: "..."
timeout_seconds: 300
allowed_paths:
  - "src/"
  - "tests/"
forbidden_paths:
  - ".env"
  - ".git/"
metadata:
  task_id: TASK-0001
```

## CLIResponse

```yaml
exit_code: 0
stdout: "..."
stderr: "..."
duration_ms: 12000
files_changed: []
error: null
```

---

# 7. Tool Permission Boundary

Adapter phải tôn trọng permission boundary.

Mặc định:

- Không đọc `.env`.
- Không xóa `.git/`.
- Không chạy destructive command.
- Không truy cập network nếu không được phép.
- Không ghi ngoài workspace nếu không được phép.

---

# 8. Timeout Policy

Mọi adapter call phải có timeout.

Không có call vô hạn.

Nếu timeout:

- Ghi lỗi.
- Tóm tắt trạng thái.
- Trả control về Orchestrator.

---

# 9. Error Format

Adapter error phải có cấu trúc:

```yaml
error:
  type: "timeout"
  message: "Ollama request timed out"
  retryable: true
  raw: "optional short raw error"
```

Không trả raw exception dài không xử lý.

---

# 10. Usage Logging

Adapter phải log:

- Provider.
- Model/tool.
- Task ID.
- Worker type.
- Duration.
- Token usage nếu có.
- Exit code nếu CLI.
- Retryable hay không.

---

# 11. Adapter Selection

Queen/Energy Manager chọn adapter dựa trên:

- Task type.
- Required reasoning.
- Cost.
- Latency.
- Local availability.
- Historical success.
- Budget.

---

# 12. Adapter Anti-patterns

- Core gọi trực tiếp provider SDK.
- Mỗi worker tự viết logic gọi model riêng.
- Không log token usage.
- Không timeout.
- Không chuẩn hóa error.
- Không permission boundary.
- Adapter tự quyết định strategy lớn.

---

# 13. MVP Adapter Scope

MVP chỉ cần:

- Ollama Adapter.
- Một cloud LLM adapter qua LiteLLM.
- Shell/Test runner adapter đơn giản.
- File system wrapper đơn giản.

Claude CLI Adapter có thể để sau hoặc dùng như bootstrap tool có kiểm soát.
