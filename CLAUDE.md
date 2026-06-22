# CLAUDE.md — Ant-Orchestrator

## 1. Ngôn ngữ làm việc

- Luôn giao tiếp với Product Owner bằng **tiếng Việt**.
- Code, tên file, tên class, tên function, commit message có thể dùng tiếng Anh theo convention kỹ thuật.
- Không tự đổi ngôn ngữ trừ khi Product Owner yêu cầu.

## 2. Mục tiêu cao nhất

Claude không chỉ cần hoàn thành task.
Claude phải hoàn thành task với mức tiêu hao năng lượng thấp nhất có thể.

Thứ tự ưu tiên:

1. Đúng yêu cầu.
2. Ít token/quota nhất có thể.
3. Code sạch, OOP, reusable, maintainable.
4. Dễ test, dễ review, dễ mở rộng.

## 3. Quy tắc token và sub-agent

- Không tự ý fork nhiều sub-agent song song.
- Mặc định chỉ dùng 1 luồng xử lý chính.
- Chỉ dùng sub-agent khi task thật sự cần phân tích độc lập.
- Trước khi dùng sub-agent phải nêu lý do rõ ràng.
- Không đọc toàn bộ repo nếu không cần thiết.
- Ưu tiên đọc file liên quan trực tiếp.

Chi tiết: `.claude/skills/token_efficiency.md`

## 4. Quy tắc coding

- Code phải tuân thủ OOP chặt chẽ khi domain phù hợp.
- Ưu tiên abstraction, interface/protocol, dependency injection.
- Không viết God Object, God Function, file quá lớn.
- Mỗi file code tối đa **350 dòng**.
- Không hard-code giá trị tự do.
- Constants phải đặt trong module constants/config phù hợp.

Chi tiết:

- `.claude/skills/oop_architecture.md`
- `.claude/skills/coding_conventions.md`
- `.claude/skills/constants_policy.md`
- `.claude/skills/file_size_policy.md`

## 5. Quy tắc làm việc

Trước khi sửa code:

1. Đọc yêu cầu.
2. Xác định phạm vi tối thiểu.
3. Đọc file liên quan.
4. Lập plan ngắn.
5. Thực hiện thay đổi nhỏ, có kiểm soát.

Sau khi sửa code:

1. Tự kiểm tra file size.
2. Tự kiểm tra constants.
3. Tự kiểm tra OOP/design.
4. Chạy test/lint nếu có thể.
5. Báo cáo ngắn, trung thực.

Checklist: `.claude/checklists/done_definition.md`

## 6. Chỉ đọc khi cần

- Đọc file hướng dẫn về tài liệu product trong: `docs/product/README.md`
- Chỉ đọc các file product document trong thư mục: `docs/product/`

## 7. Điều cấm

- Không báo hoàn thành nếu chưa kiểm chứng.
- Không tạo mock/stub để che lỗi thật nếu PO không yêu cầu.
- Không refactor lớn ngoài phạm vi task.
- Không thêm dependency mới nếu chưa có lý do mạnh.
- Không tạo file dài, code trùng lặp, magic number/string.
- Không tự thay đổi foundation/technical decision đã chốt.

## 8. Khi không chắc chắn

Nếu thiếu thông tin nhưng vẫn có thể làm an toàn, hãy nêu giả định và tiếp tục.
Nếu quyết định có thể ảnh hưởng kiến trúc lớn, dừng lại và hỏi Product Owner.
