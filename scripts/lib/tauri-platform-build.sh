#!/usr/bin/env bash
# Shared desktop bundle steps. Expects TARGET, BUNDLES, ROOT set by caller.
set -euo pipefail

: "${ROOT:?ROOT required}"
: "${TARGET:?TARGET required}"
: "${BUNDLES:?BUNDLES required}"

cd "$ROOT"

export PATH="${HOME}/.cargo/bin:${PATH}"

# setup-python on GHA can set PKG_CONFIG_PATH to its prefix and break Tauri GTK linking.
if [ "$(uname -s)" = "Linux" ]; then
  export PKG_CONFIG_PATH="/usr/lib/x86_64-linux-gnu/pkgconfig:/usr/lib/pkgconfig:/usr/share/pkgconfig${PKG_CONFIG_PATH:+:$PKG_CONFIG_PATH}"
fi
bash "$ROOT/scripts/ensure-sidecar-stubs.sh" "$TARGET" 2>/dev/null || true
bash "$ROOT/scripts/ensure-rust-toolchain.sh"

echo "==> Version $(cat VERSION)"
rustup target add "$TARGET" 2>/dev/null || true

./scripts/generate-brand-assets.sh

echo "==> Backend venv (core deps for PyInstaller)"
if [ ! -d backend/.venv ]; then
  python3 -m venv backend/.venv
fi

echo "==> Frontend production build"
(cd frontend && npm ci && npm run build)

./scripts/stage-tauri-resources.sh
./scripts/build_backend_sidecar.sh "$TARGET"

echo "==> Sync tauri.conf version"
python3 -c "
import json
from pathlib import Path
v = Path('VERSION').read_text().strip()
p = Path('desktop/src-tauri/tauri.conf.json')
c = json.loads(p.read_text())
c['version'] = v
p.write_text(json.dumps(c, indent=2) + '\n')
"

echo "==> Tauri bundle ($BUNDLES) for $TARGET"
cd desktop
if [ ! -d node_modules ]; then
  npm install
fi
export PICARD_VERSION="$(cat "$ROOT/VERSION")"
export PICARD_BUILD_SHA="$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo local)"
export PICARD_BUILD_DATE="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

cd src-tauri
export PATH="${HOME}/.cargo/bin:${PATH}"
"${HOME}/.cargo/bin/cargo" build --release --bin picard-supervisor --target "$TARGET"
PATH="${HOME}/.cargo/bin:${PATH}" npx tauri build --target "$TARGET" --bundles "$BUNDLES"

if [[ "$TARGET" == *-apple-darwin ]]; then
  APP="target/${TARGET}/release/bundle/macos/Picard.app"
  if [ -d "$APP" ]; then
    echo "==> Ad-hoc codesign Picard.app (required for valid bundle after resource binaries)"
    codesign --force --deep --sign - "$APP"
  fi
fi
