# Phase 8 — Product Owner Decision Register

> **Cập nhật**: 2026-06-29 — Toàn bộ 10 quyết định đã được Product Owner chốt.
> **Tạo**: CP0, Phase 8 startup.

---

## Quy tắc

- `APPROVED` = Product Owner đã xác nhận chính thức.
- `PENDING` = chưa có Product Owner sign-off.
- Không tự promote từ PENDING → APPROVED.

---

## PO-1 — Executable Name

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | `antctl` |
| Notes | Legacy Python entry-point `ant` có thể giữ trong thời gian migration. Không xóa âm thầm nếu test/developer workflow đang phụ thuộc. Migration plan phải rõ ràng. |

---

## PO-2 — NPM Scope Ownership

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | `@ant-orchestrator` |
| Notes | Root npm package: `@ant-orchestrator/cli` |

---

## PO-3 — Package Access: public / private

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | Local/private Verdaccio only trong Phase 8 |
| Notes | Public npm release cần approval riêng sau Phase 8 closure (xem PO-10). |

---

## PO-4 — License

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | `UNLICENSED` |
| Notes | Ngăn publish công khai. Sẽ được thay đổi khi có approval release. |

---

## PO-5 — Initial Release Version

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | `0.1.0` |
| Notes | Productized MVP version. Không publish public trong Phase 8. |

---

## PO-6 — Package Author / Organization Metadata

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | `Ant-Orchestrator Project` |

---

## PO-7 — Repository / Homepage Metadata

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | Dùng repository metadata chính thức hiện tại; không tạo homepage giả |

---

## PO-8 — Windows-only hay Multi-platform trong Phase 8

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | Windows x64 only |
| Notes | CP2 spike chạy trên Windows x64. Các platform khác cần spike riêng. |

---

## PO-9 — Python Package: publish hay chỉ build artifact

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | Python wheel là internal build artifact; không publish PyPI |

---

## PO-10 — Public Package Release thuộc Phase 8 hay chuẩn bị

| Field | Value |
|---|---|
| Status | APPROVED |
| Value | Public npm release cần approval riêng sau Phase 8 closure |
| Notes | Phase 8 kết thúc ở Verdaccio local integration test. |

---

## Additional decisions

### Executable alias

- Không expose npm binary alias `ant` trong release đầu.
- Legacy Python entry-point có thể vẫn là `ant` trong thời gian migration.
- Phase 8 phải có migration plan rõ ràng (documented tại CP5).

---

## Lịch sử thay đổi

| Date | Change | Author |
|---|---|---|
| 2026-06-29 | Tạo decision register, toàn bộ PENDING | CP0 Phase 8 startup |
| 2026-06-29 | Cập nhật tất cả APPROVED theo Product Owner sign-off | docs(decision) commit |
