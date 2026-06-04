#!/usr/bin/env python3
"""Copy platform installers from CI artifacts into a flat upload directory."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from generate_release_manifest import PLATFORM_EXTENSIONS, PLATFORM_PATTERNS, find_asset


def main() -> int:
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <artifacts-dir> <output-dir>", file=sys.stderr)
        return 2

    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)

    if not src.is_dir():
        print(f"Artifacts dir missing: {src}", file=sys.stderr)
        return 1

    staged: list[Path] = []
    for platform, patterns in PLATFORM_PATTERNS.items():
        hit = find_asset(src, patterns, PLATFORM_EXTENSIONS[platform])
        if not hit:
            print(f"No installer for {platform}", file=sys.stderr)
            continue
        out = dest / hit.name
        shutil.copy2(hit, out)
        staged.append(out)
        print(f"Staged {hit.name} ({platform})")

    if not staged:
        print("No installers staged", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
