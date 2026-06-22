# Claude Operating Decisions

## COD-001 — Tiếng Việt là ngôn ngữ giao tiếp chuẩn

Claude phải giao tiếp với Product Owner bằng tiếng Việt để giữ sự nhất quán trong quá trình phát triển.

## COD-002 — CLAUDE.md phải ngắn

`CLAUDE.md` chỉ là entrypoint. Rule chi tiết phải tách vào `.claude/skills/` để giảm token vô ích.

## COD-003 — Không uncontrolled sub-agent

Claude không được tự ý fork nhiều sub-agent song song. Đây là rủi ro lớn nhất gây bùng nổ token/quota.

## COD-004 — File code tối đa 350 dòng

Giới hạn này giúp giảm context cost, tăng maintainability và buộc thiết kế module rõ ràng.

## COD-005 — Constants bắt buộc

Không hard-code magic string/number trong business logic. Các giá trị tự do phải đi qua constants, enums hoặc config.

## COD-006 — OOP và abstraction là mặc định cho core infrastructure

Ant-Orchestrator là core infrastructure, vì vậy code phải ưu tiên interface, adapter, dependency injection và khả năng mở rộng.
