#!/usr/bin/env python3
"""Download and cache GLiNER small model for local entity extraction."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

# Load backend/.env when run directly
_env = BACKEND / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    from app.config import settings

    try:
        from gliner import GLiNER
    except ImportError:
        print("Install gliner: pip install gliner torch", file=sys.stderr)
        return 1

    dest = settings.picard_data_dir / "models" / settings.ner_model_name
    dest.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {settings.ner_hub_model_id} -> {dest}")
    model = GLiNER.from_pretrained(settings.ner_hub_model_id)
    model.save_pretrained(str(dest))
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
