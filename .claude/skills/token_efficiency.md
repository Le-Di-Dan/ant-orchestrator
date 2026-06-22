# Skill — Token Efficiency

## Mục tiêu

Giảm token, quota, thời gian và sự chú ý của con người khi Claude CLI làm việc.

## Quy tắc bắt buộc

### 1. Không đọc quá rộng

Không dùng chiến thuật đọc toàn bộ repo trước khi hiểu task.

Thứ tự đọc:

1. File được Product Owner chỉ định.
2. File import trực tiếp từ file đó.
3. Test liên quan.
4. Tài liệu liên quan trong `docs/` hoặc `.claude/`.

### 2. Không lặp lại nội dung dài

Không paste lại file dài trong câu trả lời.
Chỉ tóm tắt phần thay đổi quan trọng.

### 3. Không sinh plan quá dài

Plan tối đa 5 bước.
Mỗi bước một dòng.

### 4. Không tự mở rộng scope

Chỉ làm đúng task.
Nếu thấy vấn đề ngoài scope, ghi vào mục `Đề xuất sau`, không tự làm.

### 5. Ưu tiên sửa nhỏ

Ưu tiên patch nhỏ, rõ, dễ review.
Không rewrite toàn bộ module nếu không cần.

## Khi nào được đọc thêm file?

Chỉ đọc thêm khi:

- Cần hiểu interface.
- Cần tìm source của bug.
- Cần đảm bảo không phá contract.
- Cần chạy test/lint đúng.

## Báo cáo token-conscious

Báo cáo cuối nên gồm:

- Đã sửa gì.
- File nào bị ảnh hưởng.
- Đã kiểm tra gì.
- Rủi ro còn lại.

Không viết báo cáo dài kiểu marketing.
