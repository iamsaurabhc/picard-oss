#!/usr/bin/env python3
"""Download the fastembed ONNX model into .picard-data/models/fastembed (one-time)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

_env = BACKEND / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    try:
        import fastembed  # noqa: F401
    except ImportError:
        print("Install fastembed: pip install fastembed", file=sys.stderr)
        return 1

    from app.config import settings
    from app.services.chunk_embeddings import (
        embedding_dims_for_model,
        ensure_embedding_model,
    )

    os.environ.setdefault("ENABLE_HYBRID_SEARCH", "true")
    settings.enable_hybrid_search = True

    cache = settings.embedding_model_cache_path
    dims = embedding_dims_for_model(settings.embedding_model_id)

    print(f"Model: {settings.embedding_model_id} (dim={dims})")
    print(f"Cache: {cache}")
    print("Downloading / verifying ONNX weights (may take a minute on first run)...")

    if not ensure_embedding_model():
        print("Embedding model setup failed.", file=sys.stderr)
        return 1
    print("Embedding model is ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
