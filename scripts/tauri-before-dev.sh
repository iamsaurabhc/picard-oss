#!/usr/bin/env bash
# Started by Tauri beforeDevCommand (cwd is usually desktop/src-tauri).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/frontend"
exec npm run dev
