from __future__ import annotations

import os
from pathlib import Path

from packaging import version as pkg_version

_REPO_VERSION = Path(__file__).resolve().parents[2] / "VERSION"
_BUNDLED_VERSION = Path(__file__).resolve().parent / "defaults" / "version.txt"


def normalize_version(raw: str) -> str:
    return raw.strip().lstrip("vV")


def read_version() -> str:
    env = os.environ.get("PICARD_VERSION")
    if env:
        return normalize_version(env)
    if _BUNDLED_VERSION.is_file():
        return normalize_version(_BUNDLED_VERSION.read_text())
    if _REPO_VERSION.is_file():
        return normalize_version(_REPO_VERSION.read_text())
    return "0.1.0"


def is_version_newer(latest: str, current: str) -> bool:
    latest_n = normalize_version(latest)
    current_n = normalize_version(current)
    if not latest_n or not current_n or latest_n == current_n:
        return False
    try:
        return pkg_version.parse(latest_n) > pkg_version.parse(current_n)
    except Exception:
        return False


def build_metadata() -> dict[str, str | None]:
    return {
        "version": read_version(),
        "channel": os.environ.get("PICARD_CHANNEL", "stable"),
        "build_sha": os.environ.get("PICARD_BUILD_SHA"),
        "build_date": os.environ.get("PICARD_BUILD_DATE"),
    }
