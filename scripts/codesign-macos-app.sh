#!/usr/bin/env bash
# Ad-hoc (or Developer ID) sign a macOS .app after Tauri/PyInstaller bundle.
# Shallow `codesign --deep` breaks the bundle ("damaged" on launch); sign Mach-O inside-out.
set -euo pipefail

APP="${1:?Usage: codesign-macos-app.sh /path/to/App.app [codesign-identity]}"
IDENTITY="${2:--}"

if [ ! -d "$APP" ]; then
  echo "Not a directory: $APP" >&2
  exit 1
fi

sign_macho() {
  local f="$1"
  if file "$f" 2>/dev/null | grep -q "Mach-O"; then
    codesign --force --sign "$IDENTITY" "$f"
  fi
}

echo "==> Signing nested Mach-O in $(basename "$APP")"
while IFS= read -r -d '' f; do
  sign_macho "$f"
done < <(find "$APP/Contents" -type f -print0)

if [ -d "$APP/Contents/Frameworks" ]; then
  while IFS= read -r -d '' fw; do
    codesign --force --sign "$IDENTITY" "$fw"
  done < <(find "$APP/Contents/Frameworks" -depth \( -name "*.framework" -o -name "*.dylib" \) -print0)
fi

echo "==> Signing app bundle"
codesign --force --sign "$IDENTITY" "$APP"

codesign --verify --deep --strict "$APP"
echo "Codesign OK: $APP"
