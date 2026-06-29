# Phase 8 CP2 — Native Packaging Feasibility Spike Report

> **Verdict**: `PYINSTALLER NATIVE SPIKE: CONDITIONAL PASS`
> **Date**: 2026-06-29
> **Approach**: PyInstaller 6.21.0 `onedir`, Windows x64

---

## 1. Environment

| Item | Value |
|---|---|
| OS | Windows 11 Pro 10.0.26100 (reported as Windows 10 in platform.release) |
| Architecture | AMD64 (x64) |
| Python | 3.11.8 (tags/v3.11.8:db85d51, Feb 6 2024) |
| PyInstaller | 6.21.0 |
| LangGraph | latest (checkpoint.sqlite confirmed) |
| LiteLLM | 1.89.3 |
| FastAPI | 0.115.14 |
| tiktoken | 0.13.0 |
| certifi | bundled |
| Windows Defender real-time | **DISABLED** (see Defender section) |

---

## 2. Build Command

```bash
# From scripts/spikes/
pyinstaller --clean --noconfirm native_probe.spec
```

Spec file: `scripts/spikes/native_probe.spec`

Key spec options:
- `onedir` mode (EXE + `_internal/` directory)
- `datas`: certifi CA bundle, litellm entire package, tiktoken_ext
- `hiddenimports`: langgraph, litellm, fastapi, uvicorn, tiktoken, tiktoken_ext.openai_public, sqlite3, _sqlite3

---

## 3. Bundle Structure

```
native_probe/
├── native_probe.exe          (25.5 MB — launcher)
└── _internal/
    ├── litellm/              (model prices, JSON data files)
    ├── certifi/              (cacert.pem)
    ├── tiktoken_ext/         (cl100k_base encoding)
    ├── langgraph/            (submodules)
    ├── pydantic_core/        (compiled)
    ├── aiohttp/              (async HTTP)
    └── ...                   (272→6164 files after litellm/tiktoken data)
```

Total size: **138.2 MB** (6,164 files)

---

## 4. Import Results

| Check | Status | Notes |
|---|---|---|
| python_runtime | PASS | Python 3.11.8, `frozen=True` |
| platform_architecture | PASS | Windows 10 AMD64 64bit |
| version_module_prototype | PASS | version=0.1.0-dev serialized OK |
| sqlite_import | PASS | sqlite_version=3.43.1 |
| sqlite_crud | PASS | CREATE/INSERT/SELECT/DELETE in temp dir |
| sqlite_json1 | PASS | json_extract ok |
| langgraph_import | PASS | |
| langgraph_checkpoint_sqlite | PASS | SqliteSaver importable |
| litellm_import | PASS | (after adding litellm+tiktoken data) |
| fastapi_import | PASS | version=0.115.14 |
| uvicorn_import | PASS | |
| ca_certificates_certifi | PASS | bundle=`_internal/certifi/cacert.pem` |
| ssl_context_creation | PASS | |
| package_resource_loading | PASS | sqlite3 spec found |
| unicode_argument | PASS | NFC normalized, len=18 |
| current_working_directory | PASS | |
| path_with_spaces | PASS | temp path with spaces read/write OK |
| stdout | PASS | |
| stderr | PASS | |
| temp_directory_cleanup | PASS | |

**Total: 20/20 PASS** (final build, after fixes)

---

## 5. SQLite Results

- Import: PASS (sqlite_version=3.43.1)
- CRUD: PASS (create table, insert, select, delete, commit)
- JSON1: PASS (`json_extract('{"a":1}', '$.a')` → 1)

---

## 6. Certificate Results

- certifi bundle: PASS — located at `_internal/certifi/cacert.pem` inside bundle
- SSL context creation: PASS — `ssl.create_default_context()` succeeds
- Bundle path: certifi correctly reads from `_internal/certifi/` not system path

---

## 7. Version Results

- `frozen=True` confirmed in bundle
- `sys.executable` points to bundle .exe
- Version-module prototype: serialized to JSON correctly

---

## 8. Path / Unicode Results

- Path with spaces: PASS — `C:\Users\ADMIN\AppData\Local\Temp\ant probe clean test\native_probe\native_probe.exe`
- File I/O in spaced temp dir: PASS
- Unicode string normalization: PASS (NFC, length 18)

---

## 9. Defender Results

> **CONDITION**: Windows Defender real-time monitoring was **DISABLED** on the test machine
> (`Get-MpPreference` returned `DisableRealtimeMonitoring: True`).

- Bundle was **not blocked** during build or execution.
- No threat detections reported by `Get-MpThreatDetection`.
- **Cannot confirm Defender compatibility** — real-time protection was off.

### Required follow-up

Before production packaging:
1. Enable Windows Defender real-time protection.
2. Run the same bundle (or production build) without exclusion.
3. Confirm no quarantine, no false positive.
4. If false positive occurs: apply authenticode signing or contact Microsoft for whitelisting.

This is a **known and mitigatable** condition, not a fundamental feasibility blocker.

---

## 10. Size / Startup Metrics

| Metric | Value |
|---|---|
| Bundle size | 138.2 MB |
| File count | 6,164 |
| Cold startup | ~2,513 ms |
| Warm startup | ~2,378 ms |
| EXE size | 25.5 MB |

**Note on startup time**: 2.4–2.5s cold startup is acceptable for CLI tool but may need optimization before release. Primary cost is DLL loading and litellm/tiktoken initialization. Options: lazy-import litellm (only when provider call needed), `onefile` with extraction caching, or startup profiling.

---

## 11. Missing Imports (resolved)

Two import issues found and fixed during spike:

| Issue | Root cause | Fix |
|---|---|---|
| `litellm` — FileNotFoundError: `model_prices_and_context_window_backup.json` | LiteLLM reads JSON data at import time; file not in bundle | Add `('.../.venv/Lib/site-packages/litellm', 'litellm')` to `datas` |
| `litellm` — ValueError: Unknown encoding `cl100k_base` | tiktoken reads encoding data from `tiktoken_ext` package at runtime | Add `('.../.venv/Lib/site-packages/tiktoken_ext', 'tiktoken_ext')` + hiddenimports |

Both issues are **known PyInstaller/litellm patterns** with clear mitigations.

---

## 12. Security Observations

- Bundle is unsigned (no authenticode certificate).
- All Python bytecode is frozen inside `PYZ-00.pyz` (standard PyInstaller).
- No secrets, API keys, or provider credentials included in bundle.
- Probe source only contains stdlib + dependency imports — no business logic.
- Third-party DLLs included from venv (pydantic_core, aiohttp, etc.) — standard packaging.

---

## 13. Third-Party License Observations

- litellm: MIT — included in bundle
- langchain/langgraph: MIT — included
- PyInstaller bootloader: GPL-2.0 with exception (linking exception covers user app)
- tiktoken: MIT — included
- certifi: MPL-2.0 — CA bundle included
- fastapi: MIT — included
- All major dependencies appear permissively licensed.

**Formal license audit required before public release** (not blocking spike verdict).

---

## 14. Build Iterations

| Iteration | Result | Fix applied |
|---|---|---|
| Build 1 | 19/20 — litellm FileNotFoundError | Add `datas: litellm` |
| Build 2 | 19/20 — litellm tiktoken ValueError | Add `datas: tiktoken_ext` + hiddenimports |
| Build 3 | 20/20 PASS | Final |

---

## 15. Verdict

```
PYINSTALLER NATIVE SPIKE: CONDITIONAL PASS
```

### PASS conditions
- All 20 mandatory feasibility checks PASS in clean bundle environment.
- Python not required in PATH at runtime (`frozen=True`).
- SQLite, LangGraph, LiteLLM, FastAPI, certifi all correctly bundled.
- Bundle runs from path with spaces outside source checkout.
- Exit code propagation correct (0=success, 1=failure).
- litellm data file and tiktoken encoding issues resolved with `datas` spec entries.

### Conditions (must resolve before production)

| Condition | Severity | Action |
|---|---|---|
| Defender real-time was disabled | HIGH | Re-test with Defender enabled; apply authenticode signing if false positive |
| Startup time ~2.5s cold | MEDIUM | Profile and optimize before release (lazy litellm import) |
| Bundle size 138 MB | LOW | Acceptable for initial release; optimize if needed |
| Formal license audit | LOW | Required before public release, not before development |

---

## 16. Recommendation

**Proceed to CP3 Production Workflow Wiring** after Product Owner review.

The PyInstaller `onedir` approach is technically feasible. The two import issues found (litellm data files, tiktoken encoding) are standard PyInstaller patterns with documented solutions — not architectural blockers.

The Defender condition is the only significant uncertainty. It should be tested as a separate task before CP8 (platform package creation), not before CP3.

**ADR-0010 can be updated to ACCEPTED** pending Product Owner confirmation of this report and the Defender re-test commitment.
