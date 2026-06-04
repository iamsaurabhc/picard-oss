#!/usr/bin/env bash
# Build PyInstaller backend into Tauri resources (onedir — stable inside .app bundle).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -u "$ROOT")"
else
  ROOT="${ROOT//\\//}"
fi
RES_BACKEND="$ROOT/desktop/src-tauri/resources/backend"

cd "$ROOT/backend"
PYI_VENV=".venv-pyi"
if [ ! -d "$PYI_VENV" ]; then
  python3 -m venv "$PYI_VENV"
fi

# Platform-specific venv layout only; data paths stay relative to backend/ (no D:\a bash escapes).
if [ -f "$PYI_VENV/Scripts/python.exe" ]; then
  PYI_PYTHON="$PYI_VENV/Scripts/python.exe"
  DATA_SEP=";"
else
  PYI_PYTHON="$PYI_VENV/bin/python"
  DATA_SEP=":"
fi

if [ ! -f "$PYI_PYTHON" ]; then
  echo "PyInstaller venv python not found under $PYI_VENV" >&2
  exit 1
fi

"$PYI_PYTHON" -m pip install -q -r requirements-core.txt pyinstaller

add_data() {
  PYI_ARGS+=(--add-data "$1${DATA_SEP}$2")
}

add_binary() {
  PYI_ARGS+=(--add-binary "$1${DATA_SEP}$2")
}

PYI_ARGS=(--onedir --clean --name picard-backend)
add_data "app/db/init.sql" "app/db"
add_data "app/defaults/settings.json" "app/defaults"

mkdir -p vendor/tessdata
if [ ! -f vendor/tessdata/eng.traineddata ]; then
  echo "Downloading eng.traineddata for Tesseract…"
  curl -fsSL -o vendor/tessdata/eng.traineddata \
    "https://github.com/tesseract-ocr/tessdata_fast/raw/refs/heads/main/eng.traineddata"
fi
add_data "vendor/tessdata" "tessdata"

PYI_ARGS+=(--collect-all=litellm)
PYI_ARGS+=(--hidden-import=tiktoken_ext.openai_public)

mkdir -p vendor/tiktoken_cache
CL100K_URL="https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
CL100K_CACHE_KEY="$("$PYI_PYTHON" -c 'import hashlib; print(hashlib.sha1("'"${CL100K_URL}"'".encode()).hexdigest())')"
if [ ! -f "vendor/tiktoken_cache/$CL100K_CACHE_KEY" ]; then
  echo "Downloading cl100k_base.tiktoken for tiktoken…"
  curl -fsSL -o "vendor/tiktoken_cache/$CL100K_CACHE_KEY" "$CL100K_URL"
fi
add_data "vendor/tiktoken_cache" "tiktoken_cache"

# Resolve pdfium via Python (forward-slash path; safe on Windows Git Bash).
PDFIUM_PATH="$("$PYI_PYTHON" -c "
import pathlib
import liteparse
root = pathlib.Path(liteparse.__file__).resolve().parent
for name in ('pdfium.dll', 'libpdfium.dylib', 'libpdfium.so'):
    p = root / name
    if p.is_file():
        print(p.as_posix())
        break
")"
if [ -n "$PDFIUM_PATH" ]; then
  add_binary "$PDFIUM_PATH" "liteparse"
fi

rm -f picard-backend.spec
"$PYI_PYTHON" -m PyInstaller "${PYI_ARGS[@]}" \
  --hidden-import=uvicorn.logging \
  --hidden-import=uvicorn.loops \
  --hidden-import=uvicorn.loops.auto \
  --hidden-import=uvicorn.protocols \
  --hidden-import=uvicorn.protocols.http \
  --hidden-import=uvicorn.protocols.http.auto \
  --hidden-import=uvicorn.protocols.websockets \
  --hidden-import=uvicorn.protocols.websockets.auto \
  --hidden-import=uvicorn.lifespan \
  --hidden-import=uvicorn.lifespan.on \
  --collect-submodules=app \
  -y run_desktop.py

rm -rf "$RES_BACKEND"
mkdir -p "$RES_BACKEND"
if command -v rsync >/dev/null 2>&1; then
  rsync -a dist/picard-backend/ "$RES_BACKEND/"
else
  cp -a dist/picard-backend/. "$RES_BACKEND/"
fi
chmod +x "$RES_BACKEND/picard-backend" 2>/dev/null || chmod +x "$RES_BACKEND/picard-backend.exe" 2>/dev/null || true
echo "Backend onedir staged at $RES_BACKEND"
