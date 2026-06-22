# Prompt — Bắt đầu task cho Claude CLI

Dùng prompt này khi giao task mới cho Claude:

```text
Bạn đang làm việc trong dự án Ant-Orchestrator.

Ngôn ngữ giao tiếp với Product Owner: tiếng Việt.

Trước khi làm, hãy đọc CLAUDE.md và chỉ đọc thêm các skill liên quan trong .claude/skills/.

Yêu cầu quan trọng:
- Không tự ý fork nhiều sub-agent song song.
- Không đọc toàn bộ repo nếu không cần.
- Code phải tuân thủ OOP, abstraction, reusable.
- Không file code nào vượt 350 dòng.
- Không hard-code magic string/number; dùng constants/enums/config.
- Báo cáo cuối phải trung thực, ngắn gọn, có checklist kiểm chứng.

Task:
<ghi task ở đây>
```
