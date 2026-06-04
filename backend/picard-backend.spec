# -*- mode: python ; coding: utf-8 -*-
# Optional manual PyInstaller spec; CI/local builds use scripts/build_backend_sidecar.sh instead.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
PY_VER = f"{sys.version_info.major}.{sys.version_info.minor}"
SITE = ROOT / f".venv-pyi/lib/python{PY_VER}/site-packages"

datas = [
    ("app/db/init.sql", "app/db"),
    ("app/defaults/settings.json", "app/defaults"),
    (str(ROOT / "vendor/tessdata"), "tessdata"),
    (str(ROOT / "vendor/tiktoken_cache"), "tiktoken_cache"),
]
binaries = []
for name in ("libpdfium.dylib", "pdfium.dll", "libpdfium.so"):
    candidate = SITE / "liteparse" / name
    if candidate.is_file():
        binaries.append((str(candidate), "liteparse"))
        break

hiddenimports = [
    "tiktoken_ext.openai_public",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]
hiddenimports += collect_submodules("app")
tmp_ret = collect_all("litellm")
datas += tmp_ret[0]
binaries += tmp_ret[1]
hiddenimports += tmp_ret[2]

a = Analysis(
    ["run_desktop.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="picard-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="picard-backend",
)
