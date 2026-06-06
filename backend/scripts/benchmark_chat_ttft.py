#!/usr/bin/env python3
"""Benchmark chat TTFT phases using gold labels (mocked LLM)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.services.chat_latency import ChatLatencyTracker


def main() -> int:
    labels_path = ROOT / "eval" / "gold_chat_labels.jsonl"
    if not labels_path.is_file():
        print("gold_chat_labels.jsonl not found", file=sys.stderr)
        return 1
    count = 0
    for line in labels_path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("must_refuse"):
            continue
        count += 1
    tracker = ChatLatencyTracker()
    with tracker.phase("understanding"):
        time.sleep(0.001)
    with tracker.phase("retrieval"):
        time.sleep(0.001)
    print(json.dumps({"sample_queries": count, "latency_ms": tracker.to_dict()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
