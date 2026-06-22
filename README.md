# Claude Operating Kit cho Ant-Orchestrator

Bộ tài liệu này dùng để hướng dẫn Claude CLI làm việc hiệu quả trong dự án Ant-Orchestrator.

Mục tiêu chính:

1. Tối ưu token và quota.
2. Không tự ý fork nhiều sub-agent song song.
3. Code theo OOP, abstraction, reusable, maintainable.
4. Tuân thủ convention, constants, giới hạn kích thước file.
5. Giao tiếp với Product Owner bằng tiếng Việt.

## Cách dùng đề xuất

Copy các file/thư mục sau vào root repository của Ant-Orchestrator:

```text
CLAUDE.md
.claude/
docs/claude/
```

`CLAUDE.md` là entrypoint ngắn cho Claude CLI. Các rule chi tiết nằm trong `.claude/skills/` và checklist nằm trong `.claude/checklists/`.

## Nguyên tắc thiết kế

- `CLAUDE.md` không được biến thành tài liệu dài.
- Rule nào dài hoặc chuyên biệt phải tách sang skill riêng.
- Claude chỉ đọc skill liên quan đến task hiện tại.
- Mọi báo cáo hoàn thành phải có checklist chứng minh.
