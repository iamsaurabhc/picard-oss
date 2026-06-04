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
5. Attach artifacts to GitHub Release.

## Tauri updater signing

Generate a keypair and set the public key in `desktop/src-tauri/tauri.conf.json` (`plugins.updater.pubkey`):

```bash
cd desktop && npx tauri signer generate -w ~/.picard-updater.key
```

Store the private key in CI as `TAURI_SIGNING_PRIVATE_KEY` for release builds.

## Code signing (production)

| Platform | Requirement |
|----------|-------------|
| macOS | Developer ID + notarization (`APPLE_CERTIFICATE`, `APPLE_ID`, `APPLE_PASSWORD`) |
| Windows | Authenticode (`WINDOWS_CERTIFICATE`) |
| Tauri updater | Generate keypair: `tauri signer generate`; set pubkey in `desktop/src-tauri/tauri.conf.json` |

## Local desktop build

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
