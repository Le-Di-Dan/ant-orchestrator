# Skill — File Size Policy

## Mục tiêu

Ngăn file phình to, giảm context cost, tăng khả năng bảo trì.

## Giới hạn cứng

- Mỗi file code tối đa **350 dòng**.
- File Markdown hướng dẫn Claude nên ngắn, ưu tiên dưới **150 dòng**.
- `CLAUDE.md` phải là entrypoint ngắn, không chứa toàn bộ rule chi tiết.

## Khi file gần vượt giới hạn

Nếu file vượt 300 dòng, Claude phải cân nhắc tách module.
Nếu file vượt 350 dòng, không được tiếp tục nhồi thêm logic trừ khi đang tạm sửa bug cực nhỏ.

## Cách tách file

Tách theo trách nhiệm:

- Interface/contract.
- Implementation.
- DTO/schema.
- Constants/enums.
- Error types.
- Use case.
- Test.

## Điều cấm

- Tạo file 500–1000 dòng.
- Gom nhiều class không liên quan vào một file.
- Tạo `utils.py` khổng lồ.
- Tạo Markdown rule dài khiến Claude phải load token vô ích.

## Báo cáo bắt buộc

Nếu có file trên 300 dòng sau khi sửa, báo rõ:

```text
File gần giới hạn:
Lý do chưa tách:
Đề xuất tách sau:
```
