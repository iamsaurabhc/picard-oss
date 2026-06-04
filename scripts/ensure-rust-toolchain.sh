#!/usr/bin/env bash
# Cargo.lock v4 requires Rust/Cargo >= 1.83 (Tauri 2.11 needs recent stable).
set -euo pipefail

CARGO_BIN="${HOME}/.cargo/bin"
export PATH="${CARGO_BIN}:${PATH}"

if ! command -v rustup >/dev/null 2>&1; then
  echo "Rust not found. Install from https://rustup.rs then re-run the build." >&2
  exit 1
fi

# shellcheck disable=SC1091
[ -f "${HOME}/.cargo/env" ] && source "${HOME}/.cargo/env"
export PATH="${CARGO_BIN}:${PATH}"

rustup update stable
rustup default stable

CARGO="${CARGO_BIN}/cargo"
RUSTC="${CARGO_BIN}/rustc"
if [ ! -x "$CARGO" ]; then
  echo "Missing $CARGO after rustup install." >&2
  exit 1
fi

SHADOW="$(command -v cargo 2>/dev/null || true)"
if [ "$SHADOW" != "$CARGO" ]; then
  echo "Note: another cargo shadows rustup: $SHADOW" >&2
  echo "Using $CARGO for this build (PATH prepends ~/.cargo/bin)." >&2
fi

CARGO_VER="$("$CARGO" --version | awk '{print $2}')"
MIN_VER="1.83.0"

version_ge() {
  local a="${1%%-*}" b="${2%%-*}"
  local IFS=.
  local -a av bv
  read -r -a av <<<"$a"
  read -r -a bv <<<"$b"
  local i
  for i in 0 1 2; do
    local ai="${av[$i]:-0}" bi="${bv[$i]:-0}"
    if ((10#$ai > 10#$bi)); then return 0; fi
    if ((10#$ai < 10#$bi)); then return 1; fi
  done
  return 0
}

if ! version_ge "$CARGO_VER" "$MIN_VER"; then
  echo "Cargo $CARGO_VER at $CARGO is too old (need >= $MIN_VER)." >&2
  echo "A system/Homebrew cargo may be first in PATH. Run:" >&2
  echo "  export PATH=\"\$HOME/.cargo/bin:\$PATH\"" >&2
  echo "  cargo --version" >&2
  exit 1
fi

echo "Using $("$RUSTC" --version) / $("$CARGO" --version)"
