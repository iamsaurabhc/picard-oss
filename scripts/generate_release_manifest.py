#!/usr/bin/env python3
"""Generate releases/manifest.json for GitHub Release / gh-pages."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "releases" / "manifest.template.json"
OUT = ROOT / "releases" / "manifest.json"
VERSION_FILE = ROOT / "VERSION"

PLATFORM_PATTERNS: dict[str, list[str]] = {
    "darwin-aarch64": ["aarch64-apple-darwin", "aarch64.dmg", "arm64.dmg"],
    "darwin-x86_64": ["x86_64-apple-darwin", "x64.dmg", "x86_64.dmg"],
    "windows-x86_64": ["x86_64-pc-windows-msvc", "x64-setup", "x64.nsis"],
    "windows-i686": ["i686-pc-windows-msvc", "i686-setup", "x86-setup"],
    "linux-x86_64": ["x86_64-unknown-linux-gnu", "amd64.deb"],
    "linux-i686": ["i686-unknown-linux-gnu", "i386.deb", "i686.deb"],
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_asset(adir: Path, patterns: list[str]) -> Path | None:
    files = sorted(adir.rglob("*"), key=lambda p: p.stat().st_size if p.is_file() else 0, reverse=True)
    for f in files:
        if not f.is_file():
            continue
        name = f.name.lower()
        if any(p.lower() in name for p in patterns):
            if name.endswith((".dmg", ".exe", ".deb", ".msi", ".app.tar.gz")):
                return f
    return None


def main() -> int:
    version = os.environ.get("PICARD_VERSION", VERSION_FILE.read_text().strip()).lstrip("v")
    tag = os.environ.get("GITHUB_REF_NAME", f"v{version}").lstrip("v")
    repo = os.environ.get("GITHUB_REPOSITORY", "iamsaurabhc/picard-oss")
    base_url = f"https://github.com/{repo}/releases/download/v{version}"

    manifest = json.loads(TEMPLATE.read_text(encoding="utf-8"))
    manifest["version"] = version
    manifest["released_at"] = datetime.now(timezone.utc).isoformat()
    manifest["notes_url"] = f"https://github.com/{repo}/releases/tag/v{version}"
    manifest["channel"] = os.environ.get("PICARD_CHANNEL", "stable")

    assets_dir = os.environ.get("RELEASE_ASSETS_DIR")
    if assets_dir:
        adir = Path(assets_dir)
        for platform, patterns in PLATFORM_PATTERNS.items():
            hit = find_asset(adir, patterns)
            if hit:
                manifest["platforms"][platform] = {
                    "url": f"{base_url}/{hit.name}",
                    "sha256": sha256_file(hit),
                    "filename": hit.name,
                }

    for key, image in manifest.get("docker", {}).items():
        if isinstance(image, str) and ":0.2.0" in image:
            manifest["docker"][key] = image.replace(":0.2.0", f":{version}")

    if os.environ.get("GITHUB_REF_NAME", "").startswith("v"):
        missing = [
            k for k, v in manifest["platforms"].items() if not (v.get("url") and v.get("sha256"))
        ]
        if missing:
            print(f"Release manifest missing platforms: {missing}", file=sys.stderr)
            return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
