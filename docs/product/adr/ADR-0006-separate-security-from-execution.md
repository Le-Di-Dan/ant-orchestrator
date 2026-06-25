# ADR-0006: Separate Security Policies from Execution Boundaries

Ngày: 2026-06-24
Trạng thái: Accepted

---

## Context

Phase 3 hiện thực hóa execution boundary, context package và energy enforcement. Trong đó cần đồng
thời hai loại thành phần khác bản chất:

- **Policy thuần logic, không side effect**: redaction (phát hiện/che secret), path policy
  (canonical path + scope), command policy (argv allowlist). Đây là logic deterministic, kiểm thử
  được mà không cần chạm filesystem hay process thật.
- **Implementation có side effect**: bounded subprocess executor, bounded filesystem adapter,
  output limiter. Đây là nơi `subprocess` và I/O thực sự xảy ra.

`PROJECT_STRUCTURE.md §3` định nghĩa package `tools/` cho "wrapper tool thực thi" (shell/git/test
runner, file patcher). Nếu đặt **tất cả** policy + runtime execution + redaction + external
capability vào `tools/`, package này sẽ trộn nhiều trách nhiệm và mất ranh giới, dễ phình thành god
package khi thêm executor về sau.

Ngoài ra `subprocess` là một năng lực nhạy cảm; `tests/test_import_boundary.py` hiện cấm `subprocess`
trên toàn `src/`. Cần confinement `subprocess` vào đúng một module có kiểm soát thay vì rải rác.

`PROJECT_STRUCTURE.md §8` cho phép mở rộng cấu trúc repo nhưng yêu cầu mọi thay đổi lớn phải có ADR,
và cấm thêm layer abstraction khi MVP chưa cần. Việc thêm top-level package là một mở rộng như vậy.

---

## Decision

Tách trách nhiệm thành hai top-level package mới, song song với cấu trúc đã có:

```text
security/                  # policy THUẦN logic, KHÔNG side effect
├── redaction/
│   ├── patterns.py
│   └── redactor.py
├── path_policy.py
└── command_policy.py

execution/                 # implementation CÓ side effect, dùng policy từ security/
├── output_limit.py
├── bounded_shell.py
└── bounded_fs.py
```

Dependency direction bắt buộc:

```text
security/  ← execution/
security/  ← context/
```

Cụ thể:

- `security/` **không** import `execution/`, `context/`, `energy/`, `workflows/`, `workers/`, adapter
  cụ thể, hay provider SDK. `security/` là primitive thuần, tái sử dụng được.
- `execution/` được phép dùng policy từ `security/` và các port ở `application/ports/`.
- `context/` được phép dùng redaction và path policy từ `security/`, nhưng **không** import
  implementation từ `execution/`; nó đọc file qua `FileSystemAdapter` *port* (bounded adapter được
  inject ở composition root).
- `subprocess` chỉ được phép xuất hiện trong `execution/bounded_shell.py`.
- Application logic phụ thuộc **port** (`AuditSink`, `FileSystemAdapter`, `ShellAdapter`,
  `EnergyManager`), không phụ thuộc adapter cụ thể.
- Phase 3 **không** xây container sandbox; `execution/` chỉ là boundary cấp process, không phải một
  layer framework tổng quát.

Package `tools/` (đã định nghĩa ở `PROJECT_STRUCTURE.md`) được giữ nguyên cho các tool-wrapper tương
lai ngoài phạm vi bounded-executor của Phase 3.

---

## Reason

- **SRP**: policy thuần tách khỏi runtime giúp mỗi module một trách nhiệm, mỗi file dưới giới hạn 350
  dòng.
- **Testability**: policy kiểm thử được mà không cần process/filesystem thật; executor kiểm thử
  riêng phần side effect.
- **Future executor**: thêm executor mới không làm phình một package tổng hợp; chỉ thêm vào
  `execution/` mà policy ở `security/` tái dùng nguyên vẹn.
- **Secret containment**: `subprocess` được giới hạn vào đúng một module, dễ audit và khóa bằng
  import-boundary test.

---

## Consequences

Tích cực:

- Ranh giới trách nhiệm rõ ràng; dependency một chiều `security → execution/context`.
- Giảm rủi ro god package; dễ review từng checkpoint.
- `security/` là primitive dùng chung cho cả execution boundary (3A) và context package (3B), tránh
  trùng lặp redaction/policy.

Đánh đổi:

- Thêm hai top-level package so với `PROJECT_STRUCTURE.md` ban đầu (được hợp thức hóa bởi ADR này
  theo §8).
- `tests/test_import_boundary.py` phải được mở rộng: khóa `security/` thuần, confine `subprocess`
  vào `execution/bounded_shell.py`, và đảm bảo inner layer không import adapter audit cụ thể.
- Cấu trúc mới **không** phải một general-purpose layer framework; không được mở rộng quá nhu cầu MVP.

---

## Follow-up

- Mở rộng import-boundary test theo từng checkpoint ngay khi package được tạo (không đợi tới cuối phase).
- Nếu sau MVP cần thêm sandbox cấp container hoặc executor phân tán, cân nhắc ADR mới — không thuộc
  phạm vi Phase 3.
