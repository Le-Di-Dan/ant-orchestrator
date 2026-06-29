# Phase 8 — Product Owner Decision Register

> **Trạng thái**: Tất cả quyết định dưới đây ở trạng thái `PENDING` trừ khi Product Owner ký.
> **Tạo**: CP0, Phase 8 startup.
> **Provisional values**: chỉ dùng nội bộ cho design và spike, không được publish.

---

## Quy tắc

- `PENDING` = chưa có Product Owner sign-off.
- `APPROVED` = Product Owner đã xác nhận bằng văn bản.
- `REJECTED` = Product Owner đã từ chối.
- Provisional value KHÔNG phải approved value.
- Không tự promote từ PENDING → APPROVED.

---

## PO-1 — Executable Name

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | `<cli-command>` |
| Dùng trong | npm `bin`, `pyproject.toml` scripts, CLI docs, all test specs |
| Notes | Toàn bộ plan và test spec dùng `<cli-command>` placeholder. Sau khi approved thay toàn bộ. |

---

## PO-2 — NPM Scope Ownership

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | TBD |
| Notes | Không tự xác nhận scope availability. Cần Product Owner chỉ định npm org hoặc unscoped. |

---

## PO-3 — Package Access: public / private

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | `private` (local Verdaccio only) |
| Notes | Không publish public trước khi approved. |

---

## PO-4 — License

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | `UNLICENSED` |
| Notes | Không tự chọn license. `UNLICENSED` ngăn publish công khai. |

---

## PO-5 — Initial Release Version

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | `0.1.0-dev` |
| Notes | Không dùng `0.1.0-dev` cho public release. |

---

## PO-6 — Package Author / Organization Metadata

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | TBD |
| Notes | Không tự điền `author`, `organization`, email vào `package.json`. |

---

## PO-7 — Repository / Homepage Metadata

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | TBD |
| Notes | Không tự điền repository URL. |

---

## PO-8 — Windows-only hay Multi-platform trong Phase 8

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | Windows x64 |
| Notes | Spike CP2 chỉ chạy trên Windows x64. Nếu Phase 8 cần macOS/Linux thì spike phải chạy lại. |

---

## PO-9 — Python Package: publish hay chỉ build artifact

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | Build artifact only (không publish PyPI) |
| Notes | Wheel chỉ dùng để tạo native executable. |

---

## PO-10 — Public Package Release thuộc Phase 8 hay chuẩn bị

| Field | Value |
|---|---|
| Status | PENDING |
| Provisional | Chuẩn bị (không release công khai trong Phase 8) |
| Notes | Phase 8 kết thúc ở CP9 integration test. CP10 là live smoke test nội bộ. |

---

## Lịch sử thay đổi

| Date | Change | Author |
|---|---|---|
| 2026-06-29 | Tạo decision register, toàn bộ PENDING | CP0 Phase 8 startup |
