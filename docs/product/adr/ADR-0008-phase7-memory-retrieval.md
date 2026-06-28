# ADR-0008: Phase 7 Memory Retrieval Architecture

Ngày: 2026-06-28
Trạng thái: Accepted

---

## Context

Phase 7 cần bổ sung memory retrieval tối thiểu vào Ant-Orchestrator. Một số ràng buộc quan trọng đã
được xác nhận qua repository audit (Phase 7 plan §A):

- Phase 7 cần **deterministic memory retrieval**: filter theo structured fields, ordering cố định,
  bounded limit — không có semantic/vector search trong MVP.
- `MemoryRecord` **không có arbitrary KV metadata**: "metadata filter" có nghĩa là filter trên
  structured fields hiện hữu (type, source, confidence, tags, task_id sau migration v4).
- Tag filtering phải **complete**: không thể dùng bounded Python candidate window (chỉ đọc N records
  rồi filter) vì sẽ bỏ sót records ngoài window khi tổng số lớn. Phải filter ở SQL level.
- **Query criteria** phải nằm ở layer mà `MemoryRepository` port có thể tham chiếu và internal
  boundary có thể dùng typed IDs/enums.
- **API phải phân biệt** `WorkflowRun` và `WorkerRun`: đây là hai entity khác nhau, phải có resource
  riêng (`/workflow-runs` và `/worker-runs`).
- **CLI/API phải dùng chung application services** qua một neutral composition root; hiện tại
  `build_workflow_services()` nằm trong `cli/` khiến API không thể import.
- `RunWorkflow.execute()` **RESUME** active run (không reject); API phải phản ánh đúng semantics này,
  không trả 409 như nếu coi create là idempotent.

---

## Decision

1. **Metadata MVP = exact filtering trên structured fields hiện hữu** (type, source, confidence,
   task_id). Không có arbitrary key-value metadata.

2. **Tag filter dùng SQL-level `json_each()`** (SQLite JSON1 extension) để đảm bảo completeness.
   Runtime phải có JSON1; nếu không, fail-fast với capability error. **Không fallback** sang Python
   candidate window filtering.

3. **`MemorySearchCriteria`** là typed dataclass ở `core/domain/` để `MemoryRepository` port tham chiếu
   mà không vi phạm dependency direction. Criteria dùng typed IDs và enums ở internal boundary.

4. **Ordering cố định newest-first** (không có sort tùy chỉnh).

5. **Neutral composition root** (`application/composition_root.py`) dùng chung cho CLI và API; loại bỏ
   dependency `cli/ → services` trực tiếp.

6. **API dùng two-step task creation và workflow execution**: tạo task trước, sau đó invoke workflow
   riêng — phản ánh đúng semantics resume của `RunWorkflow.execute()`.

7. **`WorkflowRun` và `WorkerRun` có resource/ID riêng** trong API (`/workflow-runs`, `/worker-runs`).

8. **`AuditEventType.MEMORY_RETRIEVAL`** là event type mới để audit memory retrieval operations.

---

## Consequences

**Chi phí / ràng buộc:**

- Cần **migration v4** để thêm `task_id` vào `memory_records` (prerequisite cho task_id filter).
- Runtime **phải có SQLite JSON1**; thiếu JSON1 → fail-fast, không có fallback.
- **Không có semantic/vector retrieval** trong Phase 7.
- **Không có arbitrary metadata query language**.
- **Không có production memory writer** trong Phase 7 (writer là post-MVP; integration tests seed
  records thủ công).
- Context vẫn bounded bằng `limit` parameter và `ContextBudget`.

**Tích cực:**

- Tag filter deterministic và complete (không bỏ sót record ngoài window).
- CLI và API chia sẻ cùng application services; không duplicate wiring.
- `WorkflowRun`/`WorkerRun` phân biệt rõ ràng ở API boundary.

---

## Deferred

Các hạng mục sau **không thuộc Phase 7** và bị defer:

- Semantic retrieval (embedding-based).
- Vector database integration.
- Adaptive scoring / ranking.
- Memory consolidation.
- Production memory writer service.
- Authentication và public API concerns.
- Arbitrary metadata (KV) trên `MemoryRecord`.
