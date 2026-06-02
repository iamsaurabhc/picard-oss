from __future__ import annotations

import json
import math
import shutil
from pathlib import Path


def recall_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 1.0 if not retrieved[:k] else 0.0
    top = set(retrieved[:k])
    return len(top & gold) / len(gold)


def precision_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    if k == 0:
        return 0.0
    top = set(retrieved[:k])
    if not top:
        return 0.0
    return len(top & gold) / min(k, len(retrieved))


def document_match_rate(retrieved_doc_ids: list[str], gold_doc_id: str) -> float:
    if not retrieved_doc_ids:
        return 0.0
    return 1.0 if retrieved_doc_ids[0] == gold_doc_id else 0.0


def ndcg_at_k(retrieved: list[str], gold: set[str], k: int) -> float:
    dcg = 0.0
    for i, item in enumerate(retrieved[:k]):
        if item in gold:
            dcg += 1.0 / math.log2(i + 2)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal > 0 else 0.0


def intersection_recall(returned: set[tuple[str, int]], gold: set[tuple[str, int]]) -> float:
    if not gold:
        return 1.0 if not returned else 0.0
    return len(returned & gold) / len(gold)


def intersection_precision(returned: set[tuple[str, int]], gold: set[tuple[str, int]]) -> float:
    if not returned:
        return 0.0
    return len(returned & gold) / len(returned)


def decoy_rejection_rate(returned_pages: set[tuple[str, int]], decoy_pages: set[tuple[str, int]]) -> float:
    if not decoy_pages:
        return 1.0
    rejected = decoy_pages - returned_pages
    return len(rejected) / len(decoy_pages)


def tier_a_pass(scores: dict[str, float], thresholds: dict[str, float]) -> bool:
    for key, threshold in thresholds.items():
        if scores.get(key, 0) < threshold:
            return False
    return True


def tb_cell_accuracy(correct: int, total: int) -> float:
    """TB-01: fraction of pilot cells judged accurate (manual or gold labels)."""
    if total == 0:
        return 0.0
    return correct / total
