# ADR-0005: SQLite Initial Local State

Ngày: 2026-06-22  
Trạng thái: Accepted

---

## Context

MVP cần lưu task state, worker run, logs summary, memory metadata và energy usage.

Dự án ban đầu là personal infrastructure, chưa cần multi-user database phức tạp.

---

## Decision

MVP dùng SQLite làm local state store.

---

## Reason

SQLite phù hợp vì:

- Đơn giản.
- Không cần vận hành server DB.
- Dễ backup trong `.ant/` workspace.
- Phù hợp CLI/daemon local.

---

## Consequences

Tích cực:

- Setup nhanh.
- Ít overhead.
- Phù hợp MVP.

Đánh đổi:

- Không phù hợp distributed/multi-user lớn.
- Cần migration strategy nếu chuyển Postgres sau này.

---

## Follow-up

- Thiết kế repository layer để sau này có thể đổi DB.
- Không hardcode SQLite logic rải rác khắp core.
