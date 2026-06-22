# Skill — No Uncontrolled Parallel Agents

## Mục tiêu

Ngăn Claude tự ý fork quá nhiều sub-agent song song gây bùng nổ token.

## Quy tắc mặc định

- Mặc định không dùng sub-agent.
- Mặc định không chạy nhiều hướng phân tích song song.
- Một task chỉ có một luồng reasoning chính.

## Khi nào được dùng sub-agent?

Chỉ cân nhắc khi có ít nhất một điều kiện:

1. Task rất lớn và có nhiều mảng độc lập.
2. Cần audit bảo mật độc lập.
3. Cần review kiến trúc độc lập.
4. Product Owner yêu cầu rõ.

## Giới hạn cứng

- Tối đa 1 sub-agent tại một thời điểm nếu chưa có phê duyệt.
- Không spawn nhiều sub-agent chỉ để đọc code.
- Không để sub-agent đọc toàn bộ repo.

## Trước khi dùng sub-agent phải ghi rõ

```text
Lý do dùng sub-agent:
Phạm vi sub-agent được đọc:
Output mong đợi:
Token risk:
```

Nếu không thể ghi rõ 4 dòng trên, không được dùng sub-agent.
