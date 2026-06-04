from __future__ import annotations

import httpx
from fastapi import APIRouter
from packaging import version as pkg_version

from app.config import settings
from app.version import build_metadata, read_version

router = APIRouter(prefix="/updates", tags=["updates"])


@router.get("/check")
def check_for_updates():
    meta = build_metadata()
    current = read_version()
    manifest_url = settings.release_manifest_url
    result = {
        "current_version": current,
        "channel": settings.update_channel,
        "update_available": False,
        "latest_version": current,
        "manifest_url": manifest_url,
        "download_url": None,
        "notes_url": None,
        "released_at": None,
    }
    try:
        with httpx.Client(timeout=2.5) as client:
            resp = client.get(manifest_url)
            resp.raise_for_status()
            manifest = resp.json()
    except Exception:
        return result

    latest = manifest.get("version", current)
    result["latest_version"] = latest
    result["notes_url"] = manifest.get("notes_url")
    result["released_at"] = manifest.get("released_at")

    try:
        if pkg_version.parse(latest) > pkg_version.parse(current):
            result["update_available"] = True
    except Exception:
        if latest != current:
            result["update_available"] = True

    import platform

    machine = platform.machine().lower()
    system = platform.system().lower()
    platform_key = None
    if system == "darwin":
        platform_key = "darwin-aarch64" if machine in ("arm64", "aarch64") else "darwin-x86_64"
    elif system == "windows":
        platform_key = "windows-x86_64"
    elif system == "linux":
        platform_key = "linux-x86_64"

    platforms = manifest.get("platforms") or {}
    if platform_key and platform_key in platforms:
        result["download_url"] = platforms[platform_key].get("url")
    result["build"] = meta
    return result
