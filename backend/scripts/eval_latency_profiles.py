#!/usr/bin/env python3
"""Compare chat latency profiles against gold labels (smoke eval)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.latency_profile import resolve_latency_profile


def main() -> int:
    labels = ROOT / "eval" / "gold_chat_labels.jsonl"
    rows = [json.loads(line) for line in labels.read_text().splitlines() if line.strip()]
    profiles = {}
    for name in ("quality", "balanced", "fast"):
        flags = resolve_latency_profile(name)
        profiles[name] = {
            "enable_context_ranker": flags.enable_context_ranker,
            "enable_excerpt_selector": flags.enable_excerpt_selector,
            "listing_map_reduce_min_docs": flags.listing_map_reduce_min_docs,
            "use_fast_tier_synthesis": flags.use_fast_tier_synthesis,
        }
    print(json.dumps({"gold_rows": len(rows), "profiles": profiles}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
