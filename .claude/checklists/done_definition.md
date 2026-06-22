# Checklist — Definition of Done

Claude chỉ được báo hoàn thành khi đã tự kiểm các mục sau.

## 1. Scope

- [ ] Làm đúng yêu cầu Product Owner.
- [ ] Không mở rộng scope tùy tiện.
- [ ] Nếu có giả định, đã ghi rõ.

## 2. Token/Energy

- [ ] Không đọc toàn bộ repo nếu không cần.
- [ ] Không fork nhiều sub-agent song song.
- [ ] Không paste lại nội dung dài vô ích.

## 3. Code Quality

- [ ] Code có trách nhiệm rõ ràng.
- [ ] Không tạo God class/God function.
- [ ] Có abstraction/interface khi cần.
- [ ] Core không phụ thuộc trực tiếp vendor cụ thể.

## 4. Convention

- [ ] File code không vượt 350 dòng.
- [ ] Không hard-code magic string/number.
- [ ] Constants/enums/config được đặt đúng chỗ.
- [ ] Naming rõ ràng.

## 5. Validation

- [ ] Đã chạy test/lint/typecheck nếu có thể.
- [ ] Nếu không chạy được, đã nêu lý do.
- [ ] Không báo “pass” khi chưa kiểm chứng.

## 6. Final Report

Báo cáo cuối phải ngắn gọn gồm:

```text
Đã làm:
File thay đổi:
Đã kiểm tra:
Rủi ro còn lại:
Đề xuất tiếp theo:
```
