# ADR-0009: NPM Distribution Strategy

Ngày: 2026-06-29
Trạng thái: Accepted (cho các frozen decisions) / Partial PENDING (xem bên dưới)

---

## Context

Phase 8 đưa Ant-Orchestrator ra ngoài môi trường developer sang end-user distribution. Python Core
được giữ nguyên (ADR-0001). Cần một distribution channel cho phép end user cài đặt mà không cần
tự cài Python.

---

## Quyết định

### Frozen decisions — ACCEPTED

| # | Quyết định |
|---|---|
| D1 | NPM là distribution channel chính |
| D2 | Python Core được giữ nguyên, không viết lại bằng Node.js |
| D3 | Root launcher package (`package.json`) + platform packages (`optionalDependencies`) |
| D4 | Không fallback về system Python khi runtime không tìm thấy |
| D5 | Không postinstall download mặc định |
| D6 | Không telemetry mặc định |
| D7 | Global và local npm installation đều được hỗ trợ |
| D8 | Không publish package trước Product Owner approval |

### Pending decisions — PENDING (không tự coi là approved)

| # | Quyết định | Xem |
|---|---|---|
| PO-1 | Executable name | PHASE_8_PO_DECISIONS.md |
| PO-2 | NPM scope ownership | PHASE_8_PO_DECISIONS.md |
| PO-3 | Package access public/private | PHASE_8_PO_DECISIONS.md |
| PO-4 | License | PHASE_8_PO_DECISIONS.md |
| PO-5 | Initial release version | PHASE_8_PO_DECISIONS.md |
| PO-6 | Package author/organization metadata | PHASE_8_PO_DECISIONS.md |
| PO-7 | Repository/homepage metadata | PHASE_8_PO_DECISIONS.md |
| PO-8 | Windows-only hay multi-platform trong Phase 8 | PHASE_8_PO_DECISIONS.md |
| PO-9 | Python package publish hay chỉ build artifact | PHASE_8_PO_DECISIONS.md |
| PO-10 | Public package release thuộc Phase 8 hay chuẩn bị | PHASE_8_PO_DECISIONS.md |

---

## Kiến trúc NPM distribution

```
@<scope>/<name>                    ← root launcher package (PENDING: scope, name)
  package.json
    bin: { "<cli-command>": "bin/launcher.js" }
    optionalDependencies:
      @<scope>/<name>-win-x64: "<version>"
      @<scope>/<name>-darwin-x64: "<version>"    (nếu PO-8 approve multi-platform)
      @<scope>/<name>-linux-x64: "<version>"     (nếu PO-8 approve multi-platform)

@<scope>/<name>-win-x64            ← Windows x64 platform package
  bin/
    <cli-command>.exe               (hoặc onedir bundle, xem ADR-0010)
```

Launcher script (`bin/launcher.js`) tìm platform package theo `process.platform` và `process.arch`,
sau đó `child_process.execFileSync` vào native executable.

---

## Hệ quả

**Tích cực:**
- End user chỉ cần `npm install -g <package>` (sau khi PO-1/PO-2 được chốt).
- Không cần Python trên máy end user.
- Tương thích với npm global và local install workflow.
- CI/CD có thể dùng `npx`.

**Tiêu cực / rủi ro:**
- Bundle size lớn (tùy thuộc CP2 spike result).
- Cần native executable feasibility (ADR-0010).
- Metadata pending — không thể publish cho đến khi PO decisions được chốt.

---

## Alternatives considered

| Alternative | Lý do không chọn |
|---|---|
| Publish Python package chính thức | End user vẫn phải có Python và pip |
| Brew/Chocolatey/Scoop | Không có npm-centric workflow, khó tích hợp CI |
| Docker-only distribution | Overhead quá lớn cho end user, không phải use case MVP |
| Electron wrapper | Không phù hợp với CLI-first product |

---

## Liên kết

- ADR-0001: Python-first core — preserved
- ADR-0010: Native packaging strategy — PROPOSED (spike pending)
- PHASE_8_PO_DECISIONS.md: All pending metadata decisions
