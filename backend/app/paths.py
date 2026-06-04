"""OS-default paths for installed / desktop Picard builds."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_picard_data_dir() -> Path:
    """Resolve PICARD_DATA_DIR: env override, then OS default, then cwd fallback."""
    env = os.environ.get("PICARD_DATA_DIR")
    if env:
        return Path(env).expanduser().resolve()

    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "Picard").resolve()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return (base / "Picard").resolve()
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return (Path(xdg) / "picard").resolve()
    return (Path.home() / ".local" / "share" / "picard").resolve()


def config_dir(data_dir: Path | None = None) -> Path:
    return (data_dir or resolve_picard_data_dir()) / "config"


def bundled_defaults_path() -> Path:
    rel = Path(__file__).resolve().parent / "defaults" / "settings.json"
    if rel.is_file():
        return rel
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = Path(meipass) / "app" / "defaults" / "settings.json"
        if bundled.is_file():
            return bundled
    return rel
