#!/usr/bin/env bash
# Build PyInstaller backend into Tauri resources (onedir — stable inside .app bundle).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RES_BACKEND="$ROOT/desktop/src-tauri/resources/backend"

cd "$ROOT/backend"
PYI_VENV=".venv-pyi"
if [ ! -d "$PYI_VENV" ]; then
  python3 -m venv "$PYI_VENV"
fi
# shellcheck disable=SC1091
source "$PYI_VENV/bin/activate"
pip install -q -r requirements-core.txt pyinstaller

PYI_ARGS=(
  --onedir --clean --name picard-backend
  --add-data "app/db/init.sql:app/db"
  --add-data "app/defaults/settings.json:app/defaults"
)

# Tesseract traineddata for liteparse OCR (bundled; ~4 MB eng fast model).
TESS_VENDOR="$ROOT/backend/vendor/tessdata"
mkdir -p "$TESS_VENDOR"
if [ ! -f "$TESS_VENDOR/eng.traineddata" ]; then
  echo "Downloading eng.traineddata for Tesseract…"
  curl -fsSL -o "$TESS_VENDOR/eng.traineddata" \
    "https://github.com/tesseract-ocr/tessdata_fast/raw/refs/heads/main/eng.traineddata"
fi
PYI_ARGS+=(--add-data "$TESS_VENDOR:tessdata")

# liteparse needs the pdfium shared library beside its extension (not auto-collected by PyInstaller).
PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PYI_SITE="$PYI_VENV/lib/python${PY_VER}/site-packages"
if [ ! -d "$PYI_SITE" ]; then
  echo "PyInstaller venv site-packages not found: $PYI_SITE" >&2
  exit 1
fi
# LiteLLM ships many JSON assets under subpackages; bundle the package data wholesale.
PYI_ARGS+=(--collect-all=litellm)
PYI_ARGS+=(--hidden-import=tiktoken_ext.openai_public)

# tiktoken encodings (cl100k_base) for litellm token counting in frozen builds.
TIKTOKEN_CACHE="$ROOT/backend/vendor/tiktoken_cache"
mkdir -p "$TIKTOKEN_CACHE"
CL100K_URL="https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"
CL100K_CACHE_KEY="$(python3 -c 'import hashlib; print(hashlib.sha1("'"${CL100K_URL}"'".encode()).hexdigest())')"
if [ ! -f "$TIKTOKEN_CACHE/$CL100K_CACHE_KEY" ]; then
  echo "Downloading cl100k_base.tiktoken for tiktoken…"
  curl -fsSL -o "$TIKTOKEN_CACHE/$CL100K_CACHE_KEY" "$CL100K_URL"
fi
PYI_ARGS+=(--add-data "$TIKTOKEN_CACHE:tiktoken_cache")
if [ -f "$PYI_SITE/liteparse/libpdfium.dylib" ]; then
  PYI_ARGS+=(--add-binary "$PYI_SITE/liteparse/libpdfium.dylib:liteparse")
elif [ -f "$PYI_SITE/liteparse/pdfium.dll" ]; then
  PYI_ARGS+=(--add-binary "$PYI_SITE/liteparse/pdfium.dll:liteparse")
elif [ -f "$PYI_SITE/liteparse/libpdfium.so" ]; then
  PYI_ARGS+=(--add-binary "$PYI_SITE/liteparse/libpdfium.so:liteparse")
fi

pyinstaller "${PYI_ARGS[@]}" \
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
# dist/picard-backend/ contains the executable + support files
cp -a dist/picard-backend/. "$RES_BACKEND/"
chmod +x "$RES_BACKEND/picard-backend" 2>/dev/null || chmod +x "$RES_BACKEND/picard-backend.exe" 2>/dev/null || true
echo "Backend onedir staged at $RES_BACKEND"
