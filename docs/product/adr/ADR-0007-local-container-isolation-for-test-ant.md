# ADR-0007: Local Container Isolation for Test Ant

Ngày: 2026-06-27  
Trạng thái: Accepted

---

## Context

Phase 6 đưa **Test Ant** (worker thứ hai, frozen) vào MVP: Test Ant chạy test trong execution boundary,
phân loại failure, tạo structured report, và **không được sửa canonical source/test/Git metadata**
(worker contract đọc-only).

Để Test Ant thực sự đọc-only ở **process boundary**, các biện pháp process-level đã có là không đủ:

- `cwd`, thư mục tạm, sanitized environment, command allowlist và pre/post digest chỉ giới hạn
  **initial invocation** hoặc chỉ **phát hiện** thay đổi sau khi nó xảy ra.
- Code chạy bên trong test process (test, pytest plugin, child process) vẫn có thể dùng **absolute
  path**, `open()`/`os`/`shutil`, filesystem API, hoặc absolute-path child executable để ghi đè
  canonical source/test, sửa `.git`, hoặc ghi ra ngoài execution scope.
- Pre/post digest là **detection/evidence**, không phải **prevention boundary**.

Bằng chứng môi trường: **Docker khả dụng** trên host hiện tại (Docker Desktop, Server 27.5.1) và đã
được dùng làm evidence ở Phase 5 (chạy native Linux symlink suite qua `docker run --rm -v <repo>:/src:ro
python:3.11`, có image digest cố định trong PHASE_5_COMPLETION_REPORT §J).

`ADR-0006` trước đây loại **container sandbox** khỏi MVP và yêu cầu một ADR mới nếu sau này cần
(§Follow-up). Quyết định này là ADR mới đó, với phạm vi hẹp đúng cho Test Ant.

Quyết định được **Product Owner phê duyệt** (governance decision) để gỡ blocker isolation cuối cùng của
Phase 6.

---

## Decision

Cho phép **local Docker container isolation, chỉ dành riêng cho execution của Test Ant** trong Phase 6.

- Trừu tượng hóa qua **`TestIsolationPort`**: domain/application/worker/LangGraph **không** phụ thuộc
  trực tiếp Docker; chỉ composition root inject backend cụ thể.
- **Docker là backend isolation MVP đầu tiên** (`ContainerIsolationBackend` ở tầng adapters); không
  được biến thành dependency trực tiếp của `core/domain`, `workers/`, hay `workflows/`.
- **Exact-byte** approved snapshot/source được mount **read-only** vào container.
- **Writable** chỉ gồm execution-owned runtime/output mount (hoặc tmpfs) riêng biệt.
- **Network mặc định bị vô hiệu hóa** (`--network none`) trừ khi một test profile tương lai yêu cầu rõ.
- **Environment sanitized**: secrets/host env không được truyền vào container.
- **Least privilege / non-root** khi backend hỗ trợ; rootfs read-only; resource và process-tree limits.
- **Timeout/cancellation** kết thúc **toàn bộ container/process tree**; cleanup bounded và audit được.
- **Fail closed** nếu Docker/backend không khả dụng (reason code `EXECUTION_ISOLATION_UNAVAILABLE`);
  **không** fallback sang chạy test trực tiếp trong canonical workspace.
- Image được **pin theo digest**; capability/availability được kiểm tra ở preflight.

---

## Relationship with ADR-0006

- ADR này **supersede một phần rất hẹp** của ADR-0006: **chỉ** phần loại container sandbox khỏi MVP,
  và **chỉ** đối với **isolated execution của Test Ant trong Phase 6**.
- Mọi quyết định khác của ADR-0006 **vẫn giữ nguyên hiệu lực**: tách `security/` (policy thuần) khỏi
  `execution/` (side effect); dependency direction `security/ ← execution/ ← context/`; `subprocess`
  chỉ trong `execution/bounded_shell.py`; application phụ thuộc **port** chứ không phụ thuộc adapter cụ
  thể; `execution/` không phải general-purpose layer framework.
- ADR này **không** được diễn giải thành việc container hóa toàn bộ execution layer hay toàn bộ
  Ant-Orchestrator, và **không** biến Docker thành distributed worker platform.
- Lịch sử ADR-0006 **không bị xóa hoặc viết lại**; chỉ thêm một cross-reference metadata trỏ tới ADR
  này cho phần Test Ant isolation.

---

## Alternatives considered

1. **Temp snapshot + cwd + env + command allowlist + digest (process-level).** Loại: chỉ giới hạn
   initial invocation và chỉ phát hiện thay đổi; không ngăn absolute-path/filesystem-API writes ⇒
   không phải prevention boundary.
2. **Restricted OS identity / filesystem permissions.** Loại cho MVP: phụ thuộc nền tảng, phức tạp
   trên Windows host, khó kiểm thử reproducible.
3. **Linux namespaces / bubblewrap.** Loại cho MVP: chỉ Linux, không cross-platform với host Windows
   hiện tại; giữ ở parking lot.
4. **Local Docker container (CHỌN).** Enforcement thật ở OS/container boundary; **có sẵn** trên môi
   trường; cross-platform phù hợp Windows host (Docker Desktop); **kiểm thử được** bằng integration
   test; không yêu cầu xây distributed infrastructure.
5. **Trusted-test-only threat model** (coi test code là trusted, không cần isolation enforce). Loại:
   làm yếu worker contract đọc-only và không chứng minh được bằng test; chỉ là phương án dự phòng nếu
   container bị từ chối.

Docker được chọn cho MVP Phase 6 vì: enforcement thật; có sẵn; cross-platform với Windows host; kiểm
thử được; không cần distributed infrastructure.

---

## Consequences

**Tích cực:**

- Canonical repository được bảo vệ ở **OS/container boundary**, không chỉ ở process-level.
- Child process của test bị **containment** trong cùng boundary.
- Security claim "Test Ant đọc-only, không sửa source/test/Git" **chứng minh được bằng integration
  test** (write canonical bị từ chối; canonical digest bất biến).
- Worker contract read-only được **thực thi thật**, không chỉ bằng quy ước code.

**Chi phí / đánh đổi:**

- Docker trở thành **capability requirement** cho execution của Test Ant.
- Image availability và startup overhead (mỗi attempt một container).
- Cần **image pin/digest**, cleanup, resource limits và capability checks.
- Test isolation E2E **có thể skip có lý do** trong môi trường không có Docker (gated như symlink suite
  Phase 5), nhưng **production path phải fail closed** khi backend unavailable.

---

## Security invariants (chốt trong Phase 6 plan)

- Canonical repository **không writable** từ test process.
- `.git` canonical **không expose writable** (không bind-mount).
- Source/test/config = **exact-byte** read-only mount; redaction chỉ áp dụng cho stdout/stderr/excerpt/
  audit/evidence/handoff, **không** lên source.
- Writable paths **chỉ** là execution-owned runtime/output mount.
- Child process kế thừa **cùng container boundary**.
- **Network disabled** mặc định.
- **Environment secrets không** được truyền vào.
- Process chạy **non-root/least privilege** khi backend hỗ trợ.
- Timeout/cancellation **terminate toàn bộ container/process tree**.
- Backend unavailable ⇒ **fail closed** (`EXECUTION_ISOLATION_UNAVAILABLE`), **không host fallback**.
- Pre/post canonical digest giữ làm **defense-in-depth**, không phải boundary chính.

---

## Scope exclusions

ADR này **không** cho phép: distributed execution; remote worker execution; container orchestration;
Kubernetes; general-purpose sandbox cho tất cả worker; container hóa toàn bộ Ant-Orchestrator; Test Ant
sửa code/test; auto-fix loop; Git write; worker thứ ba; bất kỳ mở rộng scope nào ngoài Phase 6.

---

## Status

`Accepted` — quyết định đã được Product Owner phê duyệt (phương án A trong
`docs/plans/PHASE_6_IMPLEMENTATION_PLAN.md §N`).
