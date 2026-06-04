# macOS install (Picard.Law OSS)

## “App is damaged and can’t be opened”

This is **not** a corrupt download. macOS Gatekeeper blocks OSS builds that are **not notarized** and marks browser downloads with **quarantine**. The dialog text is misleading.

Your DMG URL is fine, for example:

`https://github.com/iamsaurabhc/picard-oss/releases/download/v0.2.0/Picard.Law.OSS_0.2.0_aarch64.dmg`

### Quick fix (after drag to Applications)

**Option A — remove quarantine**

```bash
xattr -cr "/Applications/Picard.Law OSS.app"
open "/Applications/Picard.Law OSS.app"
```

**Option B — first launch**

Right-click **Picard.Law OSS** → **Open** → confirm **Open** once.

### If it still says “damaged” (v0.2.0 and earlier CI builds)

CI used a broken shallow `codesign --deep` step. Re-sign locally:

```bash
./scripts/codesign-macos-app.sh "/Applications/Picard.Law OSS.app"
xattr -cr "/Applications/Picard.Law OSS.app"
open "/Applications/Picard.Law OSS.app"
```

## Production fix (maintainers)

Ship **Developer ID + notarization** in [`.github/workflows/release.yml`](../.github/workflows/release.yml) (`APPLE_CERTIFICATE`, `APPLE_ID`, `APPLE_PASSWORD`). See [`docs/RELEASE.md`](RELEASE.md).

Releases from **v0.2.1+** (after the nested codesign fix) should open after quarantine removal or right-click Open even without notarization.

## Slow UI or “can’t create workspace”

**“Load failed” / empty workspaces** — often the **API is not running on 8000** (check with `curl http://127.0.0.1:8000/health`). A leftover `node` on **13130** from a previous run can make the supervisor exit and kill the backend; run `./scripts/kill-picard-ports.sh`, quit Picard (Cmd+Q), reopen.

**CORS** — the UI on **13130** must be allowed by backend CORS. Ensure `~/Library/Application Support/Picard/config/settings.json` includes `http://127.0.0.1:13130` and `http://localhost:13130` under `cors_origins`, then quit and reopen Picard. Newer builds merge these automatically on startup.

1. **Free ports** — quit Picard and any dev servers, then run `./scripts/kill-picard-ports.sh` (clears **8000**, **13130**, **3000**).
2. **Check the API** — the backend has no page at `/` (404 is normal). Use:
   ```bash
   curl -s http://127.0.0.1:8000/health
   curl -s -X POST http://127.0.0.1:8000/workspaces -H 'Content-Type: application/json' -d '{"name":"Test"}'
   ```
3. **Logs** — `~/Library/Application Support/Picard/desktop-backend.log` (PyInstaller sidecar).
4. **Desktop UI** is on **http://127.0.0.1:13130**; the API is on **http://127.0.0.1:8000** (packaged builds bake `127.0.0.1`, not `localhost`, to avoid macOS IPv6 connect delays).

## “Application error” on 127.0.0.1

Usually one of:

1. **Port 3000 conflict** — if `next dev` or Docker is using port 3000, the desktop webview can load the wrong server. Quit Picard, run `./scripts/kill-picard-ports.sh`, reopen the app only (desktop UI uses **13130** in builds after v0.2.1).
2. **Stale dev server** — stop any `npm run dev` before testing the installed `.app`.

## Install steps

1. Download the `.dmg` for your Mac (Apple Silicon → `*_aarch64.dmg`, Intel → `*_x64.dmg`).
2. Open the DMG and drag **Picard.Law OSS** to **Applications**.
3. Eject the DMG, then use Option A or B above on the copy in **Applications** (not the app still on the disk image).
