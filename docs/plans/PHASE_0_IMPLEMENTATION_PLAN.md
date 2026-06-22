# PHASE 0 — IMPLEMENTATION PLAN

Trạng thái: **Approved** — nguồn sự thật khi triển khai Phase 0.

## Bối cảnh (Context)

Repository Ant-Orchestrator (tại thời điểm lập plan) **chỉ có tài liệu** (27 file `.md`, không có
`.py`, `pyproject.toml`, `src/`, `tests/`; branch `develop`, working tree sạch). ROADMAP đặt
**Phase 0 — Project Scaffolding & Quality Tooling** làm nền móng kỹ thuật + quality gate local cho
mọi phase sau.

Bản plan này đã được Product Owner phê duyệt sau nhiều vòng review; nó định nghĩa chính xác phạm vi,
checkpoint, cấu hình tooling và validation cho Phase 0. Phase 0 **không** chứa logic nghiệp vụ
(domain/persistence/adapter/LLM/workflow) — toàn bộ thuộc Phase 1 trở đi.

---

## 7.1 Tổng quan

**Mục tiêu**: skeleton package `ant_orchestrator` cài editable được + quality gate local (lint,
format-check, type-check, file-size, test) chạy bằng **một lệnh thống nhất** + CLI Typer root app
với callback tối thiểu (`ant --help`).

**Giá trị**: guardrail tự động ngăn vi phạm chất lượng ngay từ đầu; cấu trúc module cố định trước
khi có logic.

**Ranh giới với Phase 1**: không domain model, không SQLite/persistence, không `.ant/`, không config
nghiệp vụ, không adapter/LLM/LangGraph, **không** import-boundary enforcement (đó là DoD Phase 1),
không command CLI nghiệp vụ. Các package ngoài `cli` chỉ có `__init__.py` rỗng.

**Definition of Done → tiêu chí kiểm chứng**:

| DoD (Roadmap) | Tiêu chí kiểm chứng |
|---|---|
| `pip install -e .` thành công | `python -m pip install -e ".[dev]"` exit 0; `import ant_orchestrator` chạy được |
| Lệnh check thống nhất xanh | `python -m scripts.quality.gate` chạy 5 gate, exit 0 trên skeleton |
| Script file-size chạy & pass | `python -m scripts.quality.file_size` exit 0 |
| CLI root callback phản hồi `--help` | `ant --help` exit 0, in usage |

---

## 7.2 Kết quả khảo sát repository

**Đã kiểm chứng**: `git ls-files` → 27 file `.md`; không có `.py`/`pyproject.toml`/`src/`/`tests/`.
Branch `develop`, sạch.

**Convention kế thừa**: PROJECT_STRUCTURE.md §2-3 (cây repo + 11 package); COD-004 (≤350 dòng);
COD-005 (không magic literal); coding_conventions.md (code tiếng Anh, type hint public API, import
rule core ⇏ adapters/api/cli); oop_architecture.md/COD-006 (interface-first); ADR-0001 (pyproject,
bật typing); Roadmap P0 (Ruff lint+format, mypy, pytest, **không Black**, một lệnh thống nhất, script
file-size, `ant --help`).

**Mâu thuẫn/khoảng trống**:

1. `coding_conventions.md` minh hoạ layering `application/`+`infrastructure/` khác
   `PROJECT_STRUCTURE.md`. → Phase 0 theo **PROJECT_STRUCTURE.md** (nguồn chính thức Roadmap trích).
   Không tạo `application/`/`infrastructure/`. Import-rule vẫn là nguyên tắc nhưng **chưa enforce ở
   Phase 0** (enforcement là DoD Phase 1).
2. Python version không quy định trong tài liệu frozen → đã chốt `>=3.11` (PO chấp nhận).
3. Build backend & cơ chế lệnh check: Roadmap §13.3 uỷ quyền dev team → đã chốt hatchling + Python
   gate (PO chấp nhận).

---

## 7.3 Quyết định kỹ thuật (đã chốt với PO)

### QĐ-1: Build backend = `hatchling`
src-layout tối giản, không khai báo `packages.find` thủ công, không kéo runtime dep. Loại setuptools
(verbose hơn), poetry/pdm/flit (đặc thù workflow riêng). Non-blocking.

### QĐ-2: Lệnh quality gate thống nhất = **Python package** `scripts/quality/gate.py`
Chạy: `python -m scripts.quality.gate`. Gọi từng tool qua `subprocess` với command array tường minh
(xem §7.5/§7.7). Đa nền tảng thật (không `make`/`.sh`/`.ps1`), 0 dependency mới (không nox/tox/hatch
env). Format gate dùng `ruff format --check` (không sửa file). Chạy hết mọi gate rồi tổng hợp, không
short-circuit, không che failure.

### QĐ-3: File-size checker = `scripts/quality/file_size.py` (hàm thuần + module entry)
Chạy: `python -m scripts.quality.file_size`. Thuật toán + test chi tiết ở §7.6/§7.8.

### QĐ-4: CLI entry point = `ant_orchestrator.cli.main:main` — **tạo cùng checkpoint P0.1**
Cấu trúc bắt buộc của `cli/main.py`:
```text
app = typer.Typer(help="Ant-Orchestrator CLI")

@app.callback()
def root() -> None:
    """Ant-Orchestrator CLI."""   # root callback — KHÔNG logic nghiệp vụ, chỉ tạo root CLI hợp lệ + help

def main() -> None:
    app()
```
`[project.scripts] ant = "ant_orchestrator.cli.main:main"`. Một Typer app **trống hoàn toàn** không
bảo đảm CLI hợp lệ, nên **bắt buộc** có `@app.callback()` để `ant --help` exit 0 và in Usage/help.
**Không** thêm command nghiệp vụ hay command giả. Entry point **không bao giờ** trỏ tới module chưa
tồn tại.

### QĐ-5: Dependency tối thiểu + cơ chế dev = `[project.optional-dependencies].dev`
- Runtime `[project.dependencies]`: **chỉ `typer`**.
- Dev `[project.optional-dependencies].dev`: `ruff`, `mypy`, `pytest`. (Chốt optional-dependencies,
  **không** dùng `[dependency-groups]`, để khớp `python -m pip install -e ".[dev]"`.)
- Không FastAPI/LangGraph/LiteLLM/Ollama/Black/nox/tox/pre-commit/CI.

### QĐ-6: Python = `>=3.11`; `target-version` Ruff/mypy bám theo.

### QĐ-7 (mới): Quality tooling tách **hoàn toàn** khỏi runtime package
Đặt dưới `scripts/quality/`, **không** dưới `src/ant_orchestrator/`. Runtime package không phụ thuộc
dev tooling; dev tooling không nhầm với `ant_orchestrator.tools` (dành cho tool adapter runtime ở
phase sau). Tests import hàm thuần qua `scripts.quality.*` (cơ chế import ở §7.4). Không thêm
dependency để tổ chức scripts.

### QĐ-8 (mới): Bỏ `__version__` và `py.typed` khỏi Phase 0
- **Version**: chỉ nằm trong project metadata (`[project] version`). Không tạo nguồn thứ hai
  `ant_orchestrator.__version__`. Smoke test chỉ chứng minh `import ant_orchestrator` thành công.
- **`py.typed`**: defer — không tài liệu frozen nào yêu cầu công bố Ant-Orchestrator như typed
  distribution trong Phase 0. mypy nội bộ không cần marker này.

---

## 7.4 Cấu trúc source dự kiến sau Phase 0

```text
ant_orchestrator/
├── pyproject.toml                  # build + project + scripts + deps + [tool.ruff|mypy|pytest] (THỰC)
├── README.md                       # đã có, không sửa
├── src/
│   └── ant_orchestrator/
│       ├── __init__.py             # rỗng/1-dòng docstring; KHÔNG __version__ (THỰC)
│       ├── cli/
│       │   ├── __init__.py
│       │   └── main.py             # Typer root app + callback tối thiểu + main() (THỰC)
│       ├── api/__init__.py         # placeholder cấu trúc
│       ├── core/__init__.py        # placeholder
│       ├── workflows/__init__.py   # placeholder
│       ├── adapters/__init__.py    # placeholder
│       ├── workers/__init__.py     # placeholder
│       ├── context/__init__.py     # placeholder
│       ├── memory/__init__.py      # placeholder
│       ├── energy/__init__.py      # placeholder
│       ├── tools/__init__.py       # placeholder (RUNTIME tool adapter sau, KHÔNG phải dev tooling)
│       └── config/__init__.py      # placeholder
├── scripts/                        # DEV TOOLING — ngoài runtime package
│   ├── __init__.py
│   └── quality/
│       ├── __init__.py
│       ├── constants.py            # FILE_LINE_LIMIT=350, SCAN_DIRS, EXCLUDE_DIRS, FILE_GLOB (THỰC)
│       ├── file_size.py            # hàm thuần find_oversized_files + main() (THỰC)
│       └── gate.py                 # GATES + run_gates() + main() (THỰC)
└── tests/                          # KHÔNG có __init__.py (xem cơ chế import bên dưới)
    ├── test_package_import.py
    ├── test_cli_help.py
    ├── test_file_size.py
    └── test_quality_gate.py
```

**Cơ chế import trong test (không che lỗi packaging)**:
- `import ant_orchestrator...` → qua **editable install** (`python -m pip install -e ".[dev]"`) →
  validate packaging đúng. **Không** thêm `src` vào `sys.path`/pytest `pythonpath`.
- `import scripts.quality...` → dựa trên cách gọi `python -m pytest`: khi chạy module bằng
  `python -m`, Python đưa **current working directory** vào module search path. Quality command
  (gồm test) **luôn chạy từ repository root**, nên cwd = repo root, và `scripts/` (là package thật
  với `__init__.py`, **không** thuộc runtime distribution) import được như **development package**.
  **Không** dùng pytest `pythonpath`, **không** sửa `sys.path`, **không** thêm `src` vào
  `PYTHONPATH`, **không** đóng gói `scripts` vào runtime distribution.

> **Invariant**: *Mọi quality command phải được chạy từ repository root.* Chạy ngoài repo root làm
> `scripts` không import được → quality tooling báo lỗi rõ ràng; trường hợp đó được coi là **dùng sai
> contract**, không phải lỗi của plan. Cấu trúc `scripts/quality/` giữ nguyên.

**File quan trọng**:
- `src/ant_orchestrator/__init__.py` — **thực**, rỗng/docstring; làm package import được. Không version.
- `cli/main.py` — **thực**: `app = typer.Typer(help="Ant-Orchestrator CLI")` + `@app.callback()
  def root() -> None` (root callback, KHÔNG logic nghiệp vụ) + `def main() -> None: app()`. Không
  command nghiệp vụ. Dep: `typer`.
- `scripts/quality/constants.py` — **thực**: hằng số dùng chung cho checker + test (COD-005).
- `scripts/quality/file_size.py` — **thực**: hàm thuần + `main()`. Dep: stdlib (`pathlib`, `sys`).
- `scripts/quality/gate.py` — **thực**: danh sách GATES (command array) + `run_gates(gates, runner)`
  thuần + `main()`. Dep: stdlib (`subprocess`, `sys`).
- 9 `__init__.py` placeholder (api/core/workflows/adapters/workers/context/memory/energy/config) +
  `tools/__init__.py` — rỗng, xác lập cấu trúc theo PROJECT_STRUCTURE.md, import được, không logic.

---

## 7.5 Cấu hình tooling cụ thể (chốt, không để dấu ba chấm)

### Ruff (trong `pyproject.toml`)
```toml
[tool.ruff]
target-version = "py311"
line-length = 100
extend-exclude = [
  ".git", "__pycache__", ".venv", "venv", "build", "dist",
  "*.egg-info", ".mypy_cache", ".pytest_cache", ".ruff_cache",
]

[tool.ruff.lint]
select = ["E", "W", "F", "I", "B", "UP"]
# E,W: pycodestyle (style errors/warnings)
# F  : pyflakes (unused import/var, lỗi logic cơ bản)
# I  : isort (thứ tự import nhất quán)
# B  : flake8-bugbear (bẫy runtime phổ biến)
# UP : pyupgrade (cú pháp hiện đại theo target-version)

[tool.ruff.format]
# dùng default; gate gọi `ruff format --check` (không sửa file)
```
- **per-file-ignores**: Phase 0 **không** cần (CLI chưa có command, chưa dùng `typer.Option/Argument`). Khi
  thêm `typer.Option(...)` ở phase sau, dự kiến thêm
  `[tool.ruff.lint.per-file-ignores] "src/ant_orchestrator/cli/*" = ["B008"]` (Typer cố ý dùng
  callable trong default — B008 là false-positive với Typer). Ghi rõ lý do khi thêm; **không** thêm
  trước ở Phase 0.
- Không bật toàn bộ rule để tránh false-positive; bộ trên tối giản nhưng nghiêm túc.

### mypy (trong `pyproject.toml`)
```toml
[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_ignores = true
no_implicit_reexport = true
```
- **Phạm vi**: `src/` và `scripts/` đều strict. Lệnh chuẩn: `python -m mypy src scripts`.
- **Tests**: **không** đưa vào strict type-check. Lý do: test code dùng fixture/monkeypatch/cấu trúc
  động, strict mang lại friction cao mà giá trị thấp ở skeleton; file-size vẫn bao phủ `tests/`. Có
  thể bổ sung sau nếu cần (ghi là technical debt, không phải nợ chặn).
- **Exclude**: `tests/` ngoài phạm vi (không liệt kê trong lệnh/files). **Không** tắt strict toàn
  cục, **không** ignore diện rộng để làm gate xanh.
- **Contingency**: nếu một thư viện thiếu stub gây lỗi import, dùng
  `[[tool.mypy.overrides]] module="<lib>.*" \n ignore_missing_imports = true` ở mức module + ghi lý
  do; không tắt strict. (typer hiện là typed package nên dự kiến không cần.)

### pytest (trong `pyproject.toml`)
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
```
- **Không** khai báo `pythonpath`. Test chạy sau `python -m pip install -e ".[dev]"`; package import
  qua install hợp lệ; `scripts` import nhờ `python -m pytest` đưa cwd (= repo root) vào module search
  path (§7.4).

---

## 7.6 Thuật toán file-size checker (chốt)

`scripts/quality/constants.py`:
```text
FILE_LINE_LIMIT = 350
SCAN_DIRS       = ("src", "scripts", "tests")
EXCLUDE_DIRS    = frozenset({".git","__pycache__",".venv","venv","build","dist",
                             ".mypy_cache",".pytest_cache",".ruff_cache"})  # + "*.egg-info" theo suffix
FILE_GLOB       = "*.py"
```

`scripts/quality/file_size.py` — hàm thuần:
`find_oversized_files(root: Path, limit: int, scan_dirs, exclude_dirs) -> list[tuple[Path, int]]`

Quy tắc:
- **Đếm dòng vật lý chính xác** kể cả file không kết thúc bằng newline: `line_count =
  len(text.splitlines())` (đọc UTF-8). Ví dụ `"a\nb"` → 2; `"a\nb\n"` → 2; `""` → 0.
- **Ngưỡng**: vi phạm khi `line_count > FILE_LINE_LIMIT`. ⇒ 350 dòng **accept**, 351 dòng **reject**.
- Chỉ quét `*.py` trong `SCAN_DIRS`; bỏ qua mọi đường dẫn chứa thư mục trong `EXCLUDE_DIRS` hoặc
  hậu tố `*.egg-info` (generated/vendor/cache).
- **Sort deterministic** kết quả theo relative path (so sánh chuỗi POSIX).
- **Output** mỗi vi phạm: `path` (relative, dạng POSIX) · `số dòng thực tế` · `giới hạn cho phép`.
  Ví dụ: `scripts/quality/gate.py: 372 lines (limit 350)`.
- **Exit**: `0` khi không vi phạm; `1` khi có ≥1 vi phạm.
- **Không** xây AST/literal analyzer — chỉ đếm dòng.

Test (`tests/test_file_size.py`, dùng `tmp_path`):
1. File 350 dòng → không flag.
2. File 351 dòng → flag, exit code 1.
3. File **không kết thúc bằng newline** (vd 351 dòng không có `\n` cuối) → đếm đúng, flag.
4. Exclusion: file `.py` quá dài đặt trong `__pycache__/` (hoặc dir trong EXCLUDE_DIRS) → **không** flag.
5. Nhiều file vi phạm → trả về đủ và **đúng thứ tự** sort theo path.

---

## 7.7 Unified quality gate — command array & invocation (chốt)

`scripts/quality/gate.py`:
```text
GATES = [
  ("ruff-lint",      [sys.executable, "-m", "ruff", "check", "."]),
  ("ruff-format",    [sys.executable, "-m", "ruff", "format", "--check", "."]),
  ("mypy",           [sys.executable, "-m", "mypy", "src", "scripts"]),
  ("file-size",      [sys.executable, "-m", "scripts.quality.file_size"]),
  ("pytest",         [sys.executable, "-m", "pytest"]),
]
```
- **Thứ tự cố định** như trên (lint → format-check → type → file-size → test).
- `run_gates(gates, runner) -> int`: chạy **toàn bộ** gate (không short-circuit), in summary từng
  gate (pass/fail + tên), trả `0` nếu mọi gate `0`, ngược lại `1`.
- `runner(argv) -> int` mặc định: `subprocess.run(argv).returncode`; bắt `OSError`/`FileNotFoundError`
  khi không khởi chạy được tool → chuyển thành **failure có thông báo rõ** (return mã ≠ 0), không nuốt
  exception.
- Tool **không tồn tại**: `python -m <tool>` trả mã ≠ 0 kèm `No module named <tool>` → surfaced như
  failure. (Khởi chạy lỗi cấp OS cũng được bắt như trên.)
- Đa nền tảng: chỉ dùng `sys.executable` + `-m`, không shell, không `make`. Chạy từ **repo root**
  (để `python -m` đưa cwd vào `sys.path` cho subprocess `scripts.quality.file_size`).
- Format gate **luôn** có `--check` (không sửa file).

Test (`tests/test_quality_gate.py`, inject fake `runner`):
1. **Danh sách & thứ tự command đúng**: assert `[name for name,_ in GATES]` và từng `argv` khớp kỳ
   vọng (gồm `mypy ... src scripts`, file-size là module, pytest).
2. **Ruff format có `--check`**: assert `"--check"` nằm trong argv của gate `ruff-format`.
3. **Một gate fail → tổng fail**: fake runner trả ≠0 cho đúng 1 gate → `run_gates` trả ≠0; all-pass → 0.
4. **Nhiều gate fail vẫn tổng hợp**: fake runner trả ≠0 cho nhiều gate → tất cả được chạy (đếm số
   lần gọi = số gate) và kết quả ≠0.
5. **Exception khi khởi chạy** → failure có thông báo: fake runner raise `OSError` → `run_gates`
   không vỡ, trả ≠0, ghi tên gate lỗi.

---

## 7.8 Checkpoint triển khai (thứ tự sửa, không dependency ngược)

Nguyên tắc chung mọi checkpoint: **(i)** không tạo entry point trỏ module chưa tồn tại; **(ii)**
không cấu hình gate gọi script chưa tồn tại; **(iii)** validation chạy được ngay sau checkpoint;
**(iv)** repo không bị để lại quality-gate-đỏ vì việc cố ý để dành.

### P0.1 — Packaging & minimal CLI foundation
- **Mục tiêu**: cài editable được và `ant --help` chạy (CLI tồn tại cùng lúc khai báo entry point).
- **Điều kiện bắt đầu**: repo docs-only.
- **Công việc**: `pyproject.toml` (`[build-system]` hatchling; `[project]` name/version/
  requires-python=">=3.11"/dependencies=["typer"]; `[project.optional-dependencies] dev=["ruff",
  "mypy","pytest"]`; `[project.scripts] ant="ant_orchestrator.cli.main:main"`);
  `src/ant_orchestrator/__init__.py`; `src/ant_orchestrator/cli/__init__.py`;
  `src/ant_orchestrator/cli/main.py` (**bắt buộc** `@app.callback() def root()` — root CLI hợp lệ,
  không logic nghiệp vụ). (Chưa thêm `[tool.*]` — ở P0.3.)
- **File tạo**: `pyproject.toml`, `__init__.py` (package + cli), `cli/main.py`.
- **Dependency**: typer (runtime); ruff/mypy/pytest (dev).
- **Validation**: `python -m pip install -e ".[dev]"` exit 0; `ant --help` exit 0;
  `python -c "import ant_orchestrator"`.
- **Evidence**: output cài; output `ant --help`.
- **Hoàn thành**: cài được + `ant --help` xanh (entry point KHÔNG broken).
- **Không làm**: command nghiệp vụ; `[tool.*]` config; placeholder package khác.
- **Độc lập**: entry point trỏ `cli/main.py` đã tồn tại; chưa có gate gọi gì.

### P0.2 — Source/test package skeleton
- **Mục tiêu**: đủ cây 11 package + test skeleton, import được, smoke test xanh.
- **Điều kiện**: P0.1 xong.
- **Công việc**: 9 `__init__.py` còn lại (api/core/workflows/adapters/workers/context/memory/energy/
  config) + `tools/__init__.py`; `tests/test_package_import.py` (import package + vài subpackage);
  `tests/test_cli_help.py` (`typer.testing.CliRunner` invoke `--help` → assert `exit_code == 0` và
  output chứa `Usage`/help — xác nhận root callback tạo CLI hợp lệ).
- **File tạo**: 10 `__init__.py`; 2 test file.
- **Dependency**: 0.
- **Validation**: `python -c "import ant_orchestrator.core, ant_orchestrator.adapters, ..."`;
  `python -m pytest tests/test_package_import.py tests/test_cli_help.py`.
- **Evidence**: tree; pytest pass (2 test).
- **Hoàn thành**: mọi package import được; 2 smoke test xanh.
- **Không làm**: logic nghiệp vụ trong package.
- **Độc lập**: không tham chiếu scripts/quality (chưa có); không config gate.

### P0.3 — Ruff, mypy, pytest configuration
- **Mục tiêu**: cấu hình 3 tool nghiêm túc; repo xanh với phạm vi **hiện có** (`src`).
- **Điều kiện**: P0.2 xong.
- **Công việc**: thêm `[tool.ruff]`, `[tool.ruff.lint]`, `[tool.ruff.format]`, `[tool.mypy]`,
  `[tool.pytest.ini_options]` (đúng §7.5).
- **File sửa**: `pyproject.toml`.
- **Dependency**: 0.
- **Validation**: `python -m ruff check .`; `python -m ruff format --check .`;
  `python -m mypy src` (scripts CHƯA tồn tại → phạm vi mypy ở checkpoint này chỉ `src`);
  `python -m pytest`.
- **Evidence**: output 4 lệnh.
- **Hoàn thành**: 4 lệnh xanh.
- **Không làm**: tắt rule diện rộng; `# noqa`/`type: ignore` vô lý do; trỏ mypy tới `scripts` chưa có.
- **Độc lập/độ green**: mypy chạy `src` vì scripts chưa tồn tại — sẽ mở rộng sang `src scripts` ở
  P0.4 khi scripts xuất hiện; mỗi bước đều xanh, không để lại đỏ.

### P0.4 — File-size checker
- **Mục tiêu**: checker COD-004 deterministic + test; nâng phạm vi mypy lên `src scripts`.
- **Điều kiện**: P0.3 xong.
- **Công việc**: `scripts/__init__.py`; `scripts/quality/__init__.py`;
  `scripts/quality/constants.py`; `scripts/quality/file_size.py`; `tests/test_file_size.py` (§7.6).
- **File tạo**: 4 file scripts + 1 test.
- **Dependency**: 0.
- **Validation**: có thể chạy `python -m pytest tests/test_file_size.py` riêng để chẩn đoán trước,
  nhưng **tiêu chí hoàn thành dùng full gate** (vì P0.4 thêm `.py` mới vào `scripts/` và `tests/`):
  ```bash
  python -m ruff check .
  python -m ruff format --check .
  python -m mypy src scripts
  python -m scripts.quality.file_size
  python -m pytest
  ```
- **Evidence**: output checker; full validation output.
- **Hoàn thành**: toàn bộ 5 lệnh trên xanh → repository ở trạng thái xanh sau checkpoint.
- **Không làm**: AST/literal analyzer; quét generated.
- **Độc lập**: chưa có gate gọi checker (gate ở P0.5) — checker đứng độc lập, test độc lập.

### P0.5 — Unified local quality gate
- **Mục tiêu**: một lệnh chạy 5 gate, exit≠0 khi bất kỳ gate fail; **mọi script gate đã tồn tại**.
- **Điều kiện**: P0.3 (config) + P0.4 (file-size) xong.
- **Công việc**: `scripts/quality/gate.py` (GATES + `run_gates` + `main`, §7.7);
  `tests/test_quality_gate.py` (5 test inject fake runner).
- **File tạo**: 1 script + 1 test.
- **Dependency**: 0.
- **Validation**: `python -m scripts.quality.gate` exit 0 trên skeleton; `python -m pytest
  tests/test_quality_gate.py`.
- **Evidence**: output gate (kèm exit code + summary từng gate); test aggregator.
- **Hoàn thành**: gate xanh khi sạch; test chứng minh 1 gate fail / nhiều gate fail / exception →
  tổng fail; format có `--check`; thứ tự & command đúng.
- **Không làm**: short-circuit che failure; format tự sửa.
- **Độc lập**: GATES chỉ trỏ tới tool đã cài (dev) + `scripts.quality.file_size` đã tồn tại (P0.4).

### P0.6 — Validation bổ sung cho CLI & packaging
- **Mục tiêu**: bằng chứng entry point thật + packaging hợp lệ (ngoài CliRunner ở P0.2).
- **Điều kiện**: P0.1, P0.5 xong.
- **Công việc**: `tests/test_cli_entrypoint.py` — **không** giả định venv được activate / `ant` nằm
  trên PATH. Sau `python -m pip install -e ".[dev]"`, console script `ant` **bắt buộc** tồn tại; nếu
  không, đó là **packaging failure** và test **phải fail**. Thiết kế:
  1. Resolve thư mục console scripts của **chính interpreter đang chạy test**:
     `sysconfig.get_path("scripts")` (stdlib, không thêm dependency).
  2. Xác định tên executable theo OS: `ant.exe` trên Windows, `ant` trên POSIX
     (`"ant.exe" if os.name == "nt" else "ant"`).
  3. Kiểm tra executable **tồn tại**.
  4. Nếu **không** tồn tại → test **fail** với thông báo rõ rằng editable installation hoặc
     `[project.scripts]` không hợp lệ. **Tuyệt đối không** `pytest.skip`.
  5. `subprocess.run([exe_path, "--help"])`.
  6. Assert `returncode == 0` và stdout chứa `Usage`/nội dung help dự kiến.
  Ngoài ra xác nhận `import ant_orchestrator` qua install (không qua `src` trên path).
- **File tạo**: `tests/test_cli_entrypoint.py`.
- **Dependency**: 0.
- **Validation**: `ant --help` (subprocess) exit 0; `python -m pytest tests/test_cli_entrypoint.py`;
  `python -m scripts.quality.gate` vẫn xanh.
- **Evidence**: output entry point; test pass.
- **Hoàn thành**: entry point thật hoạt động qua install; gate vẫn xanh.
- **Không làm**: thêm `build` dependency; command nghiệp vụ.
- **Độc lập**: chỉ dùng artefact đã có.

### P0.7 — Final validation & evidence
- **Mục tiêu**: chạy toàn bộ đường kiểm chứng, thu evidence, xác nhận scope.
- **Điều kiện**: P0.1–P0.6 xong.
- **Công việc**: chạy lại §7.10; thu tree, dep list, danh sách file; xác nhận không logic Phase 1,
  không file `.py` > 350 dòng. **Không** sửa ROADMAP, **không** đánh dấu COMPLETED.
- **Validation**: toàn bộ lệnh §7.10 xanh.
- **Evidence**: §7.11.
- **Hoàn thành**: mọi DoD có evidence.
- **Không làm**: cập nhật Roadmap; chèn scope Phase 1.

**Dependency graph checkpoint**:
```text
P0.1 ─▶ P0.2 ─▶ P0.3 ─▶ P0.4 ─▶ P0.5 ─▶ P0.6 ─▶ P0.7
                                  ▲                 ▲
P0.1 ────────────────────────────┘  (P0.6 cần CLI từ P0.1 + gate từ P0.5)
```
Tuyến tính, không vòng. P0.5 phụ thuộc P0.3 (config) + P0.4 (file-size). P0.6 phụ thuộc P0.1 (CLI) +
P0.5. Không checkpoint nào tham chiếu file của checkpoint sau.

---

## 7.9 Ma trận truy vết

| Yêu cầu Phase 0 | Checkpoint | File chịu trách nhiệm | Lệnh validation | Evidence |
|---|---|---|---|---|
| Package cài được + `pip install -e .` | P0.1 | `pyproject.toml`, `__init__.py` | `python -m pip install -e ".[dev]"` | output cài |
| CLI `ant --help` (entry không broken) | P0.1 | `cli/main.py`, `[project.scripts]` | `ant --help` | output |
| Cây 11 package + tests | P0.2 | 10 `__init__.py`, `tests/` | `python -m pytest tests/test_package_import.py` | tree + pass |
| CLI test (CliRunner) | P0.2 | `tests/test_cli_help.py` | `python -m pytest tests/test_cli_help.py` | pass |
| Ruff lint | P0.3 | `[tool.ruff.lint]` | `python -m ruff check .` | output |
| Ruff format-check | P0.3 | `[tool.ruff.format]` | `python -m ruff format --check .` | output |
| mypy strict | P0.3→P0.4 | `[tool.mypy]` | `python -m mypy src` → `python -m mypy src scripts` | output |
| pytest | P0.3 | `[tool.pytest.ini_options]` | `python -m pytest` | report |
| File-size ≤350 (COD-004) | P0.4 | `scripts/quality/file_size.py`, `constants.py` | `python -m scripts.quality.file_size` | output |
| Lệnh check thống nhất | P0.5 | `scripts/quality/gate.py` | `python -m scripts.quality.gate` | output + exit code |
| Entry point thật (thiếu `ant` → test fail) | P0.6 | `tests/test_cli_entrypoint.py` | `ant --help` (subprocess) | output |
| Tổng hợp DoD + evidence | P0.7 | — | toàn bộ §7.10 | §7.11 |

→ Mọi yêu cầu có checkpoint + validation + evidence; không yêu cầu nào không được phủ.

---

## 7.10 Lệnh validation dự kiến (chuẩn hóa)

> Planning **chưa chạy** lệnh cần dependency chưa cài. Mọi lệnh đa nền tảng (Windows PowerShell /
> Linux / macOS), chạy ở **repo root**.

```bash
python -m pip install -e ".[dev]"      # cài editable + dev
ant --help                              # CLI qua entry point
python -m ruff check .                  # lint
python -m ruff format --check .         # format-check (không sửa file)
python -m mypy src scripts              # type-check strict (scope cuối cùng)
python -m scripts.quality.file_size     # file-size checker
python -m pytest                        # test
python -m scripts.quality.gate          # lệnh thống nhất (chạy cả 5 gate)
```

---

## 7.11 Evidence & báo cáo hoàn thành

- Output `python -m pip install -e ".[dev]"`.
- Output `ant --help`.
- Output `python -m scripts.quality.gate` (kèm exit code + summary từng gate).
- Output `python -m scripts.quality.file_size`.
- Danh sách dependency (trích `pyproject.toml` / `pip list`).
- Tree cấu trúc package thực tế.
- Test report `pytest`.
- Danh sách file tạo/sửa.
- Xác nhận **không logic nghiệp vụ Phase 1** (api/core/... chỉ `__init__.py`).
- Xác nhận **không file `.py` > 350 dòng** (output checker).

---

## 7.12 Chiến lược test (tổng hợp)

| Test | File | Nội dung |
|---|---|---|
| Smoke import | `test_package_import.py` | `import ant_orchestrator` + vài subpackage thành công (không assert version) |
| CLI help | `test_cli_help.py` | `CliRunner` `--help` exit 0 + output chứa `Usage`/help (root callback hợp lệ) |
| Entry point thật | `test_cli_entrypoint.py` | resolve `sysconfig.get_path("scripts")` + `ant.exe`/`ant` theo OS; executable thiếu → **fail** (không skip); subprocess `--help` exit 0 + usage |
| File-size | `test_file_size.py` | 350 pass / 351 flag / no-newline đếm đúng / exclusion / nhiều vi phạm đúng thứ tự |
| Quality gate | `test_quality_gate.py` | command+thứ tự đúng / `--check` có / 1 fail→tổng fail / nhiều fail tổng hợp / exception→failure rõ |

Không test `assert True`. Gate & checker test dùng dependency injection (fake runner / `tmp_path`),
không chạy thật toàn bộ tool bên trong unit test.

---

## 7.13 Rủi ro & rollback

| Rủi ro | Kiểm soát | Rollback |
|---|---|---|
| Over-tooling | Chỉ ruff/mypy/pytest dev | Gỡ khỏi `[project.optional-dependencies].dev` |
| Dependency trùng vai trò | Ruff lo cả lint+format; không Black | — |
| Config quá lỏng/nghiêm | mypy strict + ruff rule set có chủ đích; ghi lý do mọi override | Chỉnh `[tool.*]` từng phần |
| Gate không đa nền tảng | Python `sys.executable -m`, không make/sh | Sửa GATES |
| Dev tooling lẫn runtime | Tooling ở `scripts/`, runtime ở `src/`; không import chéo | Di chuyển file |
| `scripts/` nhầm với `ant_orchestrator.tools` | Tách thư mục + ghi rõ vai trò | Đổi tên/đường dẫn |
| Test che lỗi packaging | Không pythonpath `src`; import package qua install | Xoá pythonpath nếu lỡ thêm |
| Placeholder dư thừa | Chỉ `__init__.py` cần cho cấu trúc | Xoá package thừa |
| CLI lẫn logic phase sau | `cli/main.py` chỉ root app + callback tối thiểu + main() | Gỡ command |
| File-size false-positive | EXCLUDE_DIRS + đếm `splitlines`; test fixture | Sửa exclude trong constants |
| Generated/cache làm gate lỗi | exclude dùng chung; ruff/mypy có cache riêng | Bổ sung exclude |
| mypy chặn vì thiếu stub | override module-level có lý do, không tắt strict | Điều chỉnh override |
| Entry point broken / packaging sai | CLI + entry point cùng P0.1; `test_cli_entrypoint.py` **fail** (không skip) khi `ant` thiếu → phát hiện packaging failure sớm | Sửa `cli/main.py`/`[project.scripts]` |
| Quality command chạy sai cwd | Invariant: mọi quality command chạy từ repo root; ngoài root → tooling báo lỗi rõ | Chạy lại từ repo root |
| Checkpoint dependency ngược | Thứ tự P0.1→P0.7 tuyến tính; gate sau checker | Revert đúng tập file checkpoint |

**Rollback theo checkpoint**: mỗi P0.x tạo tập file tách biệt, tuyến tính → `git restore`/revert đúng
tập file checkpoint mà không ảnh hưởng checkpoint trước.

---

## 7.14 Quyết định cần PO xác nhận

Đã chốt toàn bộ với PO ở vòng review trước (Python ≥3.11; hatchling; Ruff lint+format; mypy strict;
pytest; Typer runtime; unified gate Python; file-size scope src+scripts+tests; không Black/nox/tox/
pre-commit/CI; không logic Phase 1). **Không còn quyết định Blocking.** Các điểm vận hành (build
backend, cơ chế gate, dev-deps mechanism, mypy/ruff scope) đã được chốt cụ thể trong bản này.

---

## Ranh giới phạm vi Phase 0

- Chỉ scaffolding + quality tooling; **không** logic nghiệp vụ sản phẩm.
- `pyproject.toml` chỉ chứa packaging + tooling config (không dependency phase sau).
- Dependency tối thiểu: runtime `typer`; dev `ruff`, `mypy`, `pytest`.
- **Không** đưa logic Phase 1 (domain/persistence/adapter/LLM/workflow) vào.
- **Không** sửa `ROADMAP.md` hoặc tài liệu frozen; **không** tự đánh dấu Phase 0 `COMPLETED`
  (Product Owner quyết định sau khi review evidence).
