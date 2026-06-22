# Skill — Constants Policy

## Mục tiêu

Loại bỏ magic string, magic number và hard-code tự do.

## Quy tắc bắt buộc

Không hard-code các giá trị sau trong business logic:

- Model name.
- Provider name.
- Timeout.
- Retry count.
- Token budget.
- File path chuẩn.
- Status string.
- Role name.
- Event name.
- Error code.
- CLI option default.

## Nơi đặt constants

Ví dụ Python:

```text
ant/
  core/constants.py
  core/enums.py
  config/defaults.py
  adapters/ollama/constants.py
  adapters/openai/constants.py
```

## Khi nào dùng Enum?

Dùng Enum cho tập giá trị có ý nghĩa domain:

- Task status.
- Worker role.
- Provider type.
- Autonomy level.
- Energy type.

## Khi nào dùng config?

Dùng config cho giá trị có thể thay đổi theo môi trường:

- API base URL.
- Timeout.
- Model mặc định.
- Token budget.
- Database path.

## Điều cấm

```python
if status == "done":
    ...
```

Nên dùng:

```python
if status == TaskStatus.DONE:
    ...
```

## Checklist

Trước khi báo hoàn thành:

1. Có magic string/number mới không?
2. Có status/role/provider hard-code không?
3. Giá trị này nên là Enum, constants hay config?
4. Test có phụ thuộc string tự do không?
