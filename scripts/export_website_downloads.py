#!/usr/bin/env python3
"""Export legaldocx-friendly downloads.json from releases/manifest.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "releases" / "manifest.json"
OUT = ROOT / "website" / "downloads.example.json"

LABELS = {
    "darwin-aarch64": "macOS (Apple Silicon)",
    "darwin-x86_64": "macOS (Intel)",
    "windows-x86_64": "Windows (64-bit)",
    "windows-i686": "Windows (32-bit)",
    "linux-x86_64": "Linux (deb, amd64)",
    "linux-i686": "Linux (deb, i386)",
}


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else MANIFEST
    if not src.is_file():
        print(f"Missing manifest: {src}", file=sys.stderr)
        return 1

    manifest = json.loads(src.read_text(encoding="utf-8"))
    platforms = manifest.get("platforms") or {}
    primary = {}
    for key, label in LABELS.items():
        entry = platforms.get(key) or {}
        primary[key] = {
            "label": label,
            "url": entry.get("url", ""),
            "sha256": entry.get("sha256", ""),
        }

    out = {
        "version": manifest.get("version", ""),
        "released_at": manifest.get("released_at", ""),
        "notes_url": manifest.get("notes_url", ""),
        "manifest_url": "https://raw.githubusercontent.com/iamsaurabhc/picard-oss/gh-pages/releases/manifest.json",
        "primary": primary,
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
