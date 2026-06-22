# Claude Docs Index

Đây là index để Claude chỉ đọc đúng tài liệu cần thiết.

## Entry point

- `CLAUDE.md`: rule ngắn bắt buộc đọc đầu tiên.

## Skills

- `.claude/skills/token_efficiency.md`: khi task có nguy cơ tốn token/context.
- `.claude/skills/no_parallel_agents.md`: khi Claude cân nhắc dùng sub-agent.
- `.claude/skills/oop_architecture.md`: khi thiết kế/sửa core logic.
- `.claude/skills/coding_conventions.md`: khi code Python/app structure.
- `.claude/skills/constants_policy.md`: khi thêm status, provider, role, config, timeout.
- `.claude/skills/file_size_policy.md`: khi thêm/sửa file có nguy cơ dài.

## Checklists

- `.claude/checklists/pre_coding_checklist.md`: đọc trước khi bắt đầu task lớn.
- `.claude/checklists/done_definition.md`: đọc trước khi báo hoàn thành.

## Prompts

- `.claude/prompts/task_start_prompt.md`: mẫu prompt giao task cho Claude CLI.
