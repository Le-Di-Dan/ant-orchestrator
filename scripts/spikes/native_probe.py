"""
Native packaging feasibility probe — CP2 Phase 8 spike.

Checks that a bundled runtime contains all required components.
Does NOT call any provider, does NOT send network requests, does NOT use API keys.
Runs standalone — no imports from ant_orchestrator source.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import sqlite3
import ssl
import sys
import tempfile
import traceback
import unicodedata

CHECKS: list[dict[str, object]] = []


def record(name: str, status: str, detail: str = "") -> None:
    CHECKS.append({"name": name, "status": status, "detail": detail})
    icon = "PASS" if status == "PASS" else ("SKIP" if status == "SKIP" else "FAIL")
    print(f"  [{icon}] {name}: {detail}" if detail else f"  [{icon}] {name}")


def check_python_runtime() -> None:
    info = (
        f"Python {sys.version} | "
        f"executable={sys.executable} | "
        f"frozen={getattr(sys, 'frozen', False)}"
    )
    record("python_runtime", "PASS", info)


def check_platform() -> None:
    sys_info = platform.system()
    rel = platform.release()
    mach = platform.machine()
    arch = platform.architecture()[0]
    info = f"{sys_info} {rel} {mach} {arch}"
    record("platform_architecture", "PASS", info)


def check_version_module_prototype() -> None:
    version_info = {
        "name": "ant-orchestrator",
        "version": "0.1.0-dev",
        "python": sys.version,
        "frozen": getattr(sys, "frozen", False),
    }
    serialized = json.dumps(version_info)
    assert '"version"' in serialized
    record("version_module_prototype", "PASS", f"version={version_info['version']}")


def check_sqlite_import() -> None:
    record("sqlite_import", "PASS", f"sqlite_version={sqlite3.sqlite_version}")


def check_sqlite_crud() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db_path = os.path.join(tmp, "probe_test.db")
        conn = sqlite3.connect(db_path)
        try:
            conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
            conn.execute("INSERT INTO t VALUES (1, 'hello')")
            conn.commit()
            row = conn.execute("SELECT val FROM t WHERE id=1").fetchone()
            assert row is not None and row[0] == "hello"
            conn.execute("DELETE FROM t WHERE id=1")
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            assert count == 0
            record("sqlite_crud", "PASS", f"db={db_path}")
        finally:
            conn.close()


def check_sqlite_json1() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        result = conn.execute("SELECT json_extract('{\"a\":1}', '$.a')").fetchone()
        assert result is not None and result[0] == 1
        record("sqlite_json1", "PASS", "json_extract ok")
    except sqlite3.OperationalError as exc:
        record("sqlite_json1", "FAIL", str(exc))
    finally:
        conn.close()


def check_langgraph() -> None:
    try:
        import langgraph  # noqa: F401

        record("langgraph_import", "PASS")
    except ImportError as exc:
        record("langgraph_import", "FAIL", str(exc))


def check_langgraph_checkpoint_sqlite() -> None:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401

        record("langgraph_checkpoint_sqlite", "PASS")
    except ImportError as exc:
        record("langgraph_checkpoint_sqlite", "FAIL", str(exc))


def check_litellm() -> None:
    try:
        import litellm  # noqa: F401

        record("litellm_import", "PASS")
    except ImportError as exc:
        record("litellm_import", "FAIL", str(exc))


def check_fastapi() -> None:
    try:
        import fastapi

        record("fastapi_import", "PASS", f"version={fastapi.__version__}")
    except ImportError as exc:
        record("fastapi_import", "FAIL", str(exc))


def check_uvicorn() -> None:
    try:
        import uvicorn  # noqa: F401

        record("uvicorn_import", "PASS")
    except ImportError as exc:
        record("uvicorn_import", "FAIL", str(exc))


def check_ca_certificates() -> None:
    try:
        import certifi

        ca_bundle = certifi.where()
        assert os.path.isfile(ca_bundle), f"certifi bundle not found: {ca_bundle}"
        record("ca_certificates_certifi", "PASS", f"bundle={ca_bundle}")
    except ImportError:
        record("ca_certificates_certifi", "SKIP", "certifi not installed")


def check_ssl_context() -> None:
    try:
        ctx = ssl.create_default_context()
        assert ctx is not None
        record("ssl_context_creation", "PASS")
    except Exception as exc:
        record("ssl_context_creation", "FAIL", str(exc))


def check_package_resource_loading() -> None:
    spec = importlib.util.find_spec("sqlite3")
    assert spec is not None
    record("package_resource_loading", "PASS", "sqlite3 spec found")


def check_unicode_argument() -> None:
    test_str = "テスト αβγ 中文 العربية"
    normalized = unicodedata.normalize("NFC", test_str)
    assert len(normalized) > 0
    record("unicode_argument", "PASS", f"len={len(normalized)}")


def check_cwd() -> None:
    cwd = os.getcwd()
    record("current_working_directory", "PASS", f"cwd={cwd}")


def check_path_with_spaces() -> None:
    with tempfile.TemporaryDirectory(prefix="probe test ") as tmp:
        assert " " in tmp
        test_file = os.path.join(tmp, "space test.txt")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("space path test")
        with open(test_file, encoding="utf-8") as f:
            content = f.read()
        assert content == "space path test"
        record("path_with_spaces", "PASS", f"path={tmp}")


def check_stdout() -> None:
    print("  [probe] stdout write ok", flush=True)
    record("stdout", "PASS")


def check_stderr() -> None:
    print("  [probe] stderr write ok", file=sys.stderr, flush=True)
    record("stderr", "PASS")


def check_temp_directory_cleanup() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        marker = os.path.join(tmp, "marker.txt")
        with open(marker, "w") as f:
            f.write("temp")
        assert os.path.isfile(marker)
    assert not os.path.exists(tmp), f"temp dir not cleaned up: {tmp}"
    record("temp_directory_cleanup", "PASS")


def run_all_checks() -> int:
    print("=== native_probe.py — CP2 feasibility probe ===")
    print(f"frozen={getattr(sys, 'frozen', False)}, executable={sys.executable}")
    print()

    checks = [
        check_python_runtime,
        check_platform,
        check_version_module_prototype,
        check_sqlite_import,
        check_sqlite_crud,
        check_sqlite_json1,
        check_langgraph,
        check_langgraph_checkpoint_sqlite,
        check_litellm,
        check_fastapi,
        check_uvicorn,
        check_ca_certificates,
        check_ssl_context,
        check_package_resource_loading,
        check_unicode_argument,
        check_cwd,
        check_path_with_spaces,
        check_stdout,
        check_stderr,
        check_temp_directory_cleanup,
    ]

    for check_fn in checks:
        try:
            check_fn()
        except Exception as exc:
            record(check_fn.__name__, "FAIL", f"exception: {exc}\n{traceback.format_exc()}")

    print()
    print("=== RESULTS ===")
    passed = [c for c in CHECKS if c["status"] == "PASS"]
    failed = [c for c in CHECKS if c["status"] == "FAIL"]
    skipped = [c for c in CHECKS if c["status"] == "SKIP"]

    print(f"PASS: {len(passed)}  FAIL: {len(failed)}  SKIP: {len(skipped)}")
    print()

    if failed:
        print("FAILURES:")
        for c in failed:
            print(f"  {c['name']}: {c['detail']}")
        print()

    summary = {
        "probe": "native_probe",
        "python": sys.version,
        "frozen": getattr(sys, "frozen", False),
        "executable": sys.executable,
        "passed": len(passed),
        "failed": len(failed),
        "skipped": len(skipped),
        "checks": CHECKS,
    }
    print("=== JSON SUMMARY ===")
    print(json.dumps(summary, indent=2))

    return 0 if len(failed) == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all_checks())
