#!/usr/bin/env bash
# Regenerate Tauri bundle icons and Next.js app icons from baseline PNG.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ICONS="$ROOT/desktop/src-tauri/icons"
SOURCE="$ICONS/picard_logo_light_dark_bg.png"
SVG_SOURCE="$ICONS/picard.svg"

if [ ! -f "$SOURCE" ]; then
  echo "Missing baseline: $SOURCE" >&2
  exit 1
fi

echo "==> Purge generated icons (keep picard.svg + picard_logo_light_dark_bg.png)"
find "$ICONS" -mindepth 1 -maxdepth 1 ! -name 'picard.svg' ! -name 'picard_logo_light_dark_bg.png' -exec rm -rf {} +
rm -rf "$ICONS/ios" "$ICONS/android" 2>/dev/null || true

echo "==> Tauri icon set"
cd "$ROOT/desktop"
if [ ! -d node_modules ]; then
  npm install
fi
npx tauri icon "src-tauri/icons/picard_logo_light_dark_bg.png"

echo "==> Next.js app icons"
python3 <<PY
from pathlib import Path
try:
    from PIL import Image
except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pillow"])
    from PIL import Image

src = Path("$SOURCE")
app = Path("$ROOT/frontend/app")
public = Path("$ROOT/frontend/public")
app.mkdir(parents=True, exist_ok=True)
public.mkdir(parents=True, exist_ok=True)

img = Image.open(src).convert("RGBA")
for size, name in [(32, "icon.png"), (180, "apple-icon.png")]:
    out = app / name
    resized = img.copy()
    resized.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    x = (size - resized.width) // 2
    y = (size - resized.height) // 2
    canvas.paste(resized, (x, y), resized)
    canvas.save(out)
    print("Wrote", out)

svg = Path("$SVG_SOURCE")
if svg.is_file():
    (public / "picard.svg").write_bytes(svg.read_bytes())
    print("Wrote", public / "picard.svg")
PY

echo "Done. Commit icons/ outputs + frontend/app/icon.png + apple-icon.png"
