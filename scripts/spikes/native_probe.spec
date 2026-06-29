# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for CP2 native packaging feasibility spike
# Probe only — not production CLI

block_cipher = None

a = Analysis(
    ['native_probe.py'],
    pathex=[],
    binaries=[],
    datas=[
        # certifi CA bundle
        ('../../.venv/Lib/site-packages/certifi/cacert.pem', 'certifi'),
        # litellm data files (model pricing, backup JSON)
        ('../../.venv/Lib/site-packages/litellm', 'litellm'),
        # tiktoken encoding data files (cl100k_base etc.)
        ('../../.venv/Lib/site-packages/tiktoken_ext', 'tiktoken_ext'),
    ],
    hiddenimports=[
        # LangGraph core
        'langgraph',
        'langgraph.checkpoint',
        'langgraph.checkpoint.sqlite',
        'langgraph.checkpoint.sqlite.aio',
        'langgraph.graph',
        'langgraph.prebuilt',
        # LiteLLM — large package with many optional imports
        'litellm',
        'litellm.main',
        'litellm.utils',
        'litellm.exceptions',
        # FastAPI
        'fastapi',
        'fastapi.routing',
        'fastapi.responses',
        # Uvicorn
        'uvicorn',
        'uvicorn.main',
        'uvicorn.config',
        # SSL / certifi
        'ssl',
        'certifi',
        # tiktoken
        'tiktoken',
        'tiktoken.registry',
        'tiktoken_ext',
        'tiktoken_ext.openai_public',
        # SQLite
        'sqlite3',
        '_sqlite3',
        # Standard
        'json',
        'platform',
        'tempfile',
        'unicodedata',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='native_probe',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='native_probe',
)
