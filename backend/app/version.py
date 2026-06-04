from __future__ import annotations

import os
from pathlib import Path

_REPO_VERSION = Path(__file__).resolve().parents[2] / "VERSION"


def read_version() -> str:
    env = os.environ.get("PICARD_VERSION")
    if env:
        return env.strip()
    if _REPO_VERSION.is_file():
        return _REPO_VERSION.read_text().strip()
    return "0.1.0"


def build_metadata() -> dict[str, str | None]:
    return {
        "version": read_version(),
        "channel": os.environ.get("PICARD_CHANNEL", "stable"),
        "build_sha": os.environ.get("PICARD_BUILD_SHA"),
        "build_date": os.environ.get("PICARD_BUILD_DATE"),
    }
