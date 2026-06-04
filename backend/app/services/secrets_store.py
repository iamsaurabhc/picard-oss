"""Encrypted local storage for API keys (machine-bound Fernet)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from app.paths import config_dir, resolve_picard_data_dir

logger = logging.getLogger(__name__)

SECRET_KEYS = frozenset({"openai_api_key", "anthropic_api_key"})


def _fernet():
    from cryptography.fernet import Fernet

    seed = f"{os.getenv('USER', '')}:{os.getenv('USERNAME', '')}:{Path.home()}".encode()
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


def secrets_path(data_dir: Path | None = None) -> Path:
    return config_dir(data_dir or resolve_picard_data_dir()) / "secrets.enc"


def load_secrets(data_dir: Path | None = None) -> dict[str, str]:
    path = secrets_path(data_dir)
    if not path.is_file():
        return {}
    try:
        raw = _fernet().decrypt(path.read_bytes())
        data = json.loads(raw.decode("utf-8"))
        return {k: str(v) for k, v in data.items() if k in SECRET_KEYS and v}
    except Exception:
        logger.warning("Could not decrypt secrets file")
        return {}


def save_secrets(updates: dict[str, Any], data_dir: Path | None = None) -> None:
    data = data_dir or resolve_picard_data_dir()
    config_dir(data).mkdir(parents=True, exist_ok=True)
    current = load_secrets(data)
    for key in SECRET_KEYS:
        if key in updates:
            val = updates[key]
            if val is None or val == "":
                current.pop(key, None)
            else:
                current[key] = str(val).strip()
    payload = json.dumps(current).encode("utf-8")
    secrets_path(data).write_bytes(_fernet().encrypt(payload))


def secrets_status(data_dir: Path | None = None) -> dict[str, bool]:
    s = load_secrets(data_dir)
    return {f"{k}_set": bool(s.get(k)) for k in SECRET_KEYS}
