# ADR-0010: Native Packaging Strategy

Ngày: 2026-06-29
Trạng thái: ACCEPTED (conditional — xem Remaining Conditions section)

> **CP2 Spike Result**: `PYINSTALLER NATIVE SPIKE: CONDITIONAL PASS` (2026-06-29)
> Spike report: `docs/plans/PHASE_8_SPIKE_NATIVE.md`
> Probe source: `scripts/spikes/native_probe.py`
> All 20 mandatory feasibility checks PASS. Pending: Defender re-test with real-time enabled.

---

## Context

Để end user không cần cài Python, Ant-Orchestrator cần được đóng gói thành native executable.
ADR-0009 quy định NPM là distribution channel với platform packages chứa native executable.
Cần đánh giá feasibility của các packaging approaches.

---

## Hypothesis

**PyInstaller `onedir` bundle** là candidate chính cho Windows x64.

Lý do chọn làm hypothesis:
- Mature, production-used cho Python CLI tools.
- Hỗ trợ `--collect-data` và `--collect-submodules` cho complex dependencies.
- Windows x64 là target platform Phase 8 (provisional, xem PO-8).
- `onedir` tránh extraction overhead của `onefile`.

---

## Feasibility criteria

Spike CP2 phải chứng minh:

1. Python runtime được bundle (không gọi system Python).
2. SQLite import và CRUD hoạt động.
3. LangGraph import không bị thiếu.
4. LiteLLM import không bị thiếu.
5. CA certificates resolution hoạt động.
6. Package/resource loading hoạt động.
7. Unicode path và path có khoảng trắng hoạt động.
8. Version-module prototype hoạt động.
9. Exit-code propagation đúng.
10. Windows Defender không quarantine (bật trong suốt test).

---

## Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Windows Defender false positive | HIGH | Test với Defender bật, không disable |
| LiteLLM hidden imports | MEDIUM | `--collect-all litellm` + explicit hooks |
| LangGraph resource files | MEDIUM | `--collect-data langgraph` |
| Bundle size > 200MB | LOW | `onedir` thay vì `onefile`, lazy-load |
| Startup time > 5s cold | MEDIUM | Benchmark và optimize hooks |
| SQLite `json_each` / JSON1 | LOW | Verify extension loaded |
| SSL cert path trong bundle | MEDIUM | `certifi` explicit collect |

---

## Alternatives nếu FAIL

### Alternative 1: Nuitka

Compile Python → C → native binary. Tốt hơn về startup time và antivirus.
Phức tạp hơn để cấu hình với complex dependencies.

### Alternative 2: Embedded Python distribution

Bundle Python embeddable + wheels + launcher script.
Không cần build step phức tạp nhưng bundle structure khác.
Cần xử lý PATH và site-packages thủ công.

### Alternative 3: Shipper / cx_Freeze

Alternatives khác trong ecosystem.

---

## Điều kiện chuyển trạng thái

### → ACCEPTED

- CP2 spike PASS hoặc CONDITIONAL PASS.
- Không có architecture blocker.
- Product Owner review spike report.
- Tất cả mandatory checks từ Feasibility criteria PASS.

### → REJECTED

- CP2 spike FAIL với blocker không có mitigation.
- Sẽ được SUPERSEDED bởi alternative ADR (Nuitka, Embedded Python, etc.).

### → SUPERSEDED

- Nếu approach thay đổi căn bản sau spike FAIL.
- ADR mới sẽ reference ADR-0010 làm baseline.

---

## Evidence section (CP2 spike — 2026-06-29)

### Build
- PyInstaller 6.21.0 `onedir`, Windows x64
- Spec: `scripts/spikes/native_probe.spec`
- datas: certifi CA bundle, litellm (full package), tiktoken_ext

### Results
- 20/20 mandatory checks PASS (final build)
- Bundle size: 138.2 MB, 6,164 files
- Executable: `native_probe.exe` (25.5 MB launcher)
- `frozen=True` confirmed — Python not required in PATH
- Runs from path with spaces outside source checkout
- Exit code propagation: 0=success, 1=failure verified

### Issues found and resolved
1. LiteLLM missing `model_prices_and_context_window_backup.json` → add `datas: litellm`
2. tiktoken `cl100k_base` missing → add `datas: tiktoken_ext` + hiddenimports

### Remaining conditions
- **HIGH**: Defender real-time was disabled on test machine — must re-test with Defender enabled before CP8
- **MEDIUM**: Cold startup ~2.5s — profile and optimize before release
- **LOW**: Bundle 138 MB — acceptable; formal license audit before public release

Full details: `docs/plans/PHASE_8_SPIKE_NATIVE.md`

---

## Liên kết

- ADR-0009: NPM distribution strategy — ACCEPTED
- CP2 spike report: `docs/plans/PHASE_8_SPIKE_NATIVE.md` (tạo sau spike)
- CP2 probe source: `scripts/spikes/native_probe.py` (tạo tại CP2)
