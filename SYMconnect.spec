# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


server_config = Path("build-config/server_url.txt")
if not server_config.is_file():
    raise SystemExit(
        "Missing build-config/server_url.txt. Run scripts/build_windows.ps1 with -ServerUrl."
    )

a = Analysis(
    ["symconnect/desktop_app.py"],
    pathex=["."],
    binaries=[],
    datas=[
        ("symconnect/static", "symconnect/static"),
        (str(server_config), "."),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="SYMconnect",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
