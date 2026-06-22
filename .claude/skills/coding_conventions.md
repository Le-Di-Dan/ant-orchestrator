# Skill — Coding Conventions

## Mục tiêu

Giữ codebase nhất quán, dễ đọc, dễ review, dễ mở rộng.

## Quy tắc chung

- Code bằng tiếng Anh.
- Giao tiếp/report với Product Owner bằng tiếng Việt.
- Tên class dùng `PascalCase`.
- Tên function/variable dùng `snake_case` cho Python.
- Tên constants dùng `UPPER_SNAKE_CASE`.
- Không dùng abbreviation khó hiểu.

## Python convention

- Type hints bắt buộc cho public function/method.
- Public class/function nên có docstring ngắn nếu logic không hiển nhiên.
- Không swallow exception im lặng.
- Không dùng bare `except:`.
- Không dùng mutable default argument.
- Không đặt business logic trong CLI/API handler.

## Layering đề xuất

```text
ant/
  core/          # domain logic thuần
  adapters/      # claude/openai/gemini/ollama/git/shell
  application/   # use cases / workflows
  infrastructure/# sqlite, file system, process runner
  api/           # FastAPI
  cli/           # Typer CLI
```

## Import rule

- `core` không import từ `adapters`, `api`, `cli`, `infrastructure`.
- `application` có thể dùng interface từ `core`.
- `infrastructure` implement interface.
- `api` và `cli` chỉ gọi use case.

## Error handling

- Domain error phải có type rõ ràng.
- External adapter phải wrap lỗi vendor thành lỗi nội bộ.
- Error message cho PO bằng tiếng Việt nếu xuất hiện trong CLI/report.
