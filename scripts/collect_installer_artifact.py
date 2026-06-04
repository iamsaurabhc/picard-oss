#!/usr/bin/env python3
"""Pick the platform installer from a Tauri bundle tree for CI artifact upload."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <rust-target-triple>", file=sys.stderr)
        return 2

    target = sys.argv[1]
    bundle = Path("desktop/src-tauri/target") / target / "release" / "bundle"
    exts = {".dmg", ".exe", ".deb"}
    installers = [
        p for p in bundle.rglob("*") if p.is_file() and p.suffix.lower() in exts
    ]
    if not installers:
        print(f"No installer under {bundle}", file=sys.stderr)
        return 1

    hit = max(installers, key=lambda p: p.stat().st_size)
    dest = Path("release-installer")
    dest.mkdir(exist_ok=True)
    out = dest / hit.name
    shutil.copy2(hit, out)
    print(f"Installer artifact: {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
