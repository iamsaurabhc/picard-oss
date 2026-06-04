# Picard OSS release process

## Branding

Source logos (edit these only):

- [`desktop/src-tauri/icons/picard.svg`](../desktop/src-tauri/icons/picard.svg)
- [`desktop/src-tauri/icons/picard_logo_light_dark_bg.png`](../desktop/src-tauri/icons/picard_logo_light_dark_bg.png)

Regenerate Tauri + web favicons:

```bash
./scripts/generate-brand-assets.sh
```

## Versioning

- Bump [`VERSION`](../VERSION) on release.
- Tag `git tag v0.2.0 && git push origin v0.2.0`.

## CI pipeline

[`.github/workflows/release.yml`](../.github/workflows/release.yml) on tag:

1. Build and push Docker images to `ghcr.io/<repo>-backend` and `-frontend`.
2. Build Tauri bundles (macOS arm64/x64, Windows EXE, Linux DEB).
3. Generate [`releases/manifest.json`](../releases/manifest.json) with download URLs and SHA256.
4. Publish manifest to `gh-pages` at `https://raw.githubusercontent.com/iamsaurabhc/picard-oss/gh-pages/releases/manifest.json`.
5. Prune any existing assets on the GitHub Release, then attach installers + `manifest.json` only.

## Tauri updater signing

Generate a keypair and set the public key in `desktop/src-tauri/tauri.conf.json` (`plugins.updater.pubkey`):

```bash
cd desktop && npx tauri signer generate -w ~/.picard-updater.key
```

Store the private key in CI as `TAURI_SIGNING_PRIVATE_KEY` for release builds.

## macOS Gatekeeper (“damaged” dialog)

OSS CI builds are ad-hoc signed until Apple credentials are configured. Users who download from the website or GitHub may need to clear quarantine or use **right-click → Open** once. See [`docs/MACOS_INSTALL.md`](MACOS_INSTALL.md).

CI runs [`scripts/codesign-macos-app.sh`](../scripts/codesign-macos-app.sh) after each macOS bundle (nested Mach-O sign, not `codesign --deep` on the `.app` alone).

## Code signing (production)

| Platform | Requirement |
|----------|-------------|
| macOS | Developer ID + notarization (`APPLE_CERTIFICATE`, `APPLE_ID`, `APPLE_PASSWORD`) |
| Windows | Authenticode (`WINDOWS_CERTIFICATE`) |
| Tauri updater | Generate keypair: `tauri signer generate`; set pubkey in `desktop/src-tauri/tauri.conf.json` |

## Tauri dev (native shell + hot-reload UI)

Two terminals:

```bash
# Terminal 1 — API
cd backend && source .venv/bin/activate
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

# Terminal 2 — webview + Next dev (:3000)
cd desktop && npm install && npm run tauri:dev
```

`tauri dev` starts `next dev` via [`scripts/tauri-before-dev.sh`](../scripts/tauri-before-dev.sh) and opens the desktop window at `http://127.0.0.1:3000` (must match `devUrl` and `app.windows[].url` in `tauri.conf.json`). The Rust shell does **not** spawn the production sidecar in debug mode (see `Picard dev:` in the console). Release builds patch the window URL to `:13130` in [`scripts/lib/tauri-platform-build.sh`](../scripts/lib/tauri-platform-build.sh).

## Local desktop build

Desktop bundles set `NEXT_PUBLIC_API_URL=http://127.0.0.1:8000` during `npm run build` (see [`scripts/lib/tauri-platform-build.sh`](../scripts/lib/tauri-platform-build.sh)) so the webview avoids macOS `localhost` → IPv6 connect delays.

Requires **Rust stable >= 1.83** (`rustup update stable`). If `cargo --version` shows 1.71.x, a Homebrew/system cargo is shadowing rustup — run `export PATH="$HOME/.cargo/bin:$PATH"` first. The build script runs `ensure-rust-toolchain.sh` automatically.

```bash
./scripts/build-dmg-macos-arm64.sh   # Apple Silicon DMG
./scripts/build-dmg-macos-x64.sh     # Intel macOS
./scripts/build-exe-windows-x64.sh
./scripts/build-exe-windows-x86.sh
./scripts/build-deb-linux-amd64.sh

Linux i386 (`.deb`) builds are not in CI yet (GTK cross-compile); use `build-deb-linux-i386.sh` locally if needed.
```

Dev stubs (before sidecars are built):

```bash
./scripts/ensure-sidecar-stubs.sh
```

## Updates

Installed apps poll `GET /updates/check` (backend) or Tauri updater plugin against the gh-pages manifest. User data in `PICARD_DATA_DIR` is preserved across upgrades.
